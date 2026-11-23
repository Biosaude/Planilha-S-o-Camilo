import hashlib
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .material_matcher import material
from .models import QuoteError
from .validators import anvisa_key, date_value, normalized, open_xlsx, reference_key, text_value

FILENAMES = ('PLANILHA COM CÓDIGO TUSS_PARTE_1.xlsx', 'PLANILHA COM CÓDIGO TUSS_PARTE_2.xlsx')
HEADERS = {
    'code': {'tuss', 'codigo tuss', 'cod tuss', 'codigo do termo'},
    'description': {'descricao', 'descricao oficial', 'termo', 'descricao do termo', 'nome do termo'},
    'model': {'modelo', 'referencia', 'referencia modelo', 'modelo referencia', 'codigo referencia'},
    'manufacturer': {'fabricante', 'marca', 'fabricante marca'},
    'anvisa': {'anvisa', 'registro anvisa', 'registro na anvisa', 'numero anvisa'},
    'starts': {'inicio vigencia', 'data inicio vigencia', 'data de inicio de vigencia',
               'vigencia inicial', 'inicio de vigencia', 'data inicio'},
    'ends': {'fim vigencia', 'data fim vigencia', 'data de fim de vigencia',
             'vigencia final', 'fim de vigencia', 'data fim'},
    'risk': {'classe de risco', 'classe risco'},
    'technical_name': {'nome tecnico', 'denominacao tecnica'},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    sha256_part1 TEXT NOT NULL,
    sha256_part2 TEXT NOT NULL,
    count1 INTEGER NOT NULL,
    count2 INTEGER NOT NULL,
    invalid_anvisa INTEGER NOT NULL,
    shared_anvisa INTEGER NOT NULL,
    duplicate_records INTEGER NOT NULL,
    UNIQUE(sha256_part1, sha256_part2)
);
CREATE TABLE IF NOT EXISTS active_version (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    version_id INTEGER NOT NULL REFERENCES versions(id)
);
CREATE TABLE IF NOT EXISTS entries (
    version_id INTEGER NOT NULL REFERENCES versions(id),
    source INTEGER NOT NULL CHECK (source IN (1, 2)),
    sheet TEXT NOT NULL,
    row_num INTEGER NOT NULL,
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    model TEXT NOT NULL,
    manufacturer TEXT NOT NULL,
    anvisa TEXT NOT NULL,
    starts TEXT NOT NULL,
    ends TEXT NOT NULL,
    risk TEXT NOT NULL,
    technical_name TEXT NOT NULL,
    model_key TEXT NOT NULL,
    model_inferred INTEGER NOT NULL,
    anvisa_key TEXT NOT NULL,
    label_key TEXT NOT NULL,
    device_kind TEXT NOT NULL,
    PRIMARY KEY (version_id, source, sheet, row_num)
);
CREATE INDEX IF NOT EXISTS entries_model ON entries(version_id, model_key) WHERE model_key <> '';
CREATE INDEX IF NOT EXISTS entries_anvisa ON entries(version_id, anvisa_key) WHERE anvisa_key <> '';
CREATE INDEX IF NOT EXISTS entries_label ON entries(version_id, label_key);
CREATE INDEX IF NOT EXISTS entries_kind ON entries(version_id, device_kind) WHERE device_kind <> '';
"""


@dataclass(frozen=True)
class ImportReport:
    id: int
    label: str
    imported_at: str
    count1: int
    count2: int
    invalid_anvisa: int
    shared_anvisa: int
    duplicate_records: int


REPORT_FIELDS = 'id, label, imported_at, count1, count2, invalid_anvisa, shared_anvisa, duplicate_records'


def _columns(values):
    labels = [normalized(v) for v in values]
    positions = {}
    for field, aliases in HEADERS.items():
        matches = [index for index, label in enumerate(labels) if label in aliases]
        if len(matches) > 1:
            raise QuoteError('Uma base TUSS contém cabeçalhos duplicados para o mesmo campo.')
        if matches:
            positions[field] = matches[0]
    return positions if {'code', 'description'} <= positions.keys() else None


def _source_date(value):
    return date_value(value).isoformat() if value is not None and text_value(value) else ''


def _inferred_model(description):
    # Bases legadas trazem o modelo ao final do termo, após separador.
    match = re.search(r'\s+[–—-]\s+([A-Z0-9][A-Z0-9.\-/]{3,39})\s*$', description, re.I)
    return match[1] if match and any(char.isdigit() for char in match[1]) else ''


def _source_records(payload, filename, part):
    workbook = open_xlsx(payload, filename, read_only=True)
    try:
        for sheet in workbook.worksheets:
            if (sheet.max_row and sheet.max_row > 300_000) or (sheet.max_column and sheet.max_column > 128):
                raise QuoteError(f'A parte {part} excede o limite de linhas ou colunas.')
            rows = enumerate(sheet.iter_rows(max_col=min(sheet.max_column or 128, 128)), 1)
            columns = None
            content = False
            for number, cells in rows:
                if number > 100:
                    break
                values = [cell.value for cell in cells]
                content = content or any(value is not None for value in values)
                columns = _columns(values)
                if columns:
                    break
            if not columns:
                if content or (sheet.max_row or 0) > 100:
                    raise QuoteError(f'Parte {part}: uma aba não possui cabeçalho de código/termo reconhecível.')
                continue
            for number, cells in rows:
                if number > 300_000:
                    raise QuoteError(f'A parte {part} excede o limite de linhas.')
                if all(cell.value is None for cell in cells):
                    continue
                values = {key: cells[i].value for key, i in columns.items()}
                code, description = text_value(values['code']), text_value(values['description'])
                if any(cells[i].data_type in {'e', 'f'} for i in columns.values()) or not re.fullmatch(
                    r'[0-9]{6,15}', code
                ) or not normalized(description):
                    raise QuoteError(f'Parte {part}, linha {number}: código ou termo inválido.')
                try:
                    starts = _source_date(values.get('starts'))
                    ends = _source_date(values.get('ends'))
                except ValueError as exc:
                    raise QuoteError(f'Parte {part}, linha {number}: vigência inválida.') from exc
                if starts and ends and starts > ends:
                    raise QuoteError(f'Parte {part}, linha {number}: vigência inicial posterior à final.')
                model = text_value(values.get('model'))
                inferred = _inferred_model(description) if not model else ''
                anvisa = text_value(values.get('anvisa'))
                device = material(description)
                yield (
                    part, sheet.title, number, code, description, model or inferred,
                    text_value(values.get('manufacturer')), anvisa, starts, ends,
                    text_value(values.get('risk')), text_value(values.get('technical_name')),
                    reference_key(model or inferred), bool(inferred), anvisa_key(anvisa),
                    device.label, device.kind,
                )
    finally:
        workbook.close()


def _connect(path: Path, *, write=False):
    if write:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.touch(mode=0o600, exist_ok=True)
    mode = 'rw' if write else 'ro'
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=' + mode, uri=True, timeout=10)
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def _activate(connection, version):
    connection.execute(
        'INSERT INTO active_version VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET version_id=excluded.version_id',
        (version,),
    )


def import_bases(path: Path, part1: tuple[bytes, str], part2: tuple[bytes, str], label: str) -> ImportReport:
    label = label.strip()
    if not label or len(label) > 80:
        raise QuoteError('Informe um nome de versão de até 80 caracteres.')
    if part1[1] != FILENAMES[0] or part2[1] != FILENAMES[1]:
        raise QuoteError('Selecione cada planilha com o nome oficial da respectiva parte TUSS.')
    hashes = tuple(hashlib.sha256(part[0]).hexdigest() for part in (part1, part2))
    if hashes[0] == hashes[1]:
        raise QuoteError('As duas partes da base TUSS devem ser arquivos distintos.')
    try:
        with closing(_connect(path, write=True)) as db:
            db.executescript(SCHEMA)
            with db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute(
                    f'SELECT {REPORT_FIELDS} FROM versions WHERE sha256_part1=? AND sha256_part2=?', hashes
                ).fetchone()
                if existing:
                    raise QuoteError(f'Esses arquivos já foram importados como versão {existing[0]}.')
                version = db.execute(
                    """INSERT INTO versions
                    (label, imported_at, sha256_part1, sha256_part2, count1, count2, invalid_anvisa,
                     shared_anvisa, duplicate_records) VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0)""",
                    (label, datetime.now(timezone.utc).isoformat(timespec='seconds'), *hashes),
                ).lastrowid
                counts = []
                for number, part in enumerate((part1, part2), 1):
                    inserted = db.executemany(
                        'INSERT INTO entries VALUES (' + ','.join('?' * 18) + ')',
                        ((version, *record) for record in _source_records(*part, number)),
                    ).rowcount
                    if not inserted:
                        raise QuoteError(f'A parte {number} da base TUSS não contém registros.')
                    counts.append(inserted)
                invalid = db.execute(
                    "SELECT count(*) FROM entries WHERE version_id=? AND anvisa<>'' AND anvisa_key=''", (version,)
                ).fetchone()[0]
                shared = db.execute(
                    """SELECT count(*) FROM (SELECT anvisa_key FROM entries
                        WHERE version_id=? AND anvisa_key<>'' GROUP BY anvisa_key
                        HAVING count(DISTINCT code)>1)""", (version,)
                ).fetchone()[0]
                duplicate = db.execute(
                    """SELECT coalesce(sum(n-1), 0) FROM (
                        SELECT count(*) AS n FROM entries WHERE version_id=?
                        GROUP BY code, label_key, model_key, manufacturer, anvisa_key, starts, ends)""",
                    (version,),
                ).fetchone()[0]
                db.execute(
                    'UPDATE versions SET count1=?, count2=?, invalid_anvisa=?, shared_anvisa=?, duplicate_records=? WHERE id=?',
                    (*counts, invalid, shared, duplicate, version),
                )
                _activate(db, version)
                return ImportReport(*db.execute(f'SELECT {REPORT_FIELDS} FROM versions WHERE id=?', (version,)).fetchone())
    except (sqlite3.Error, OSError) as exc:
        raise QuoteError('Não foi possível gravar a base TUSS. Verifique o acesso ao banco local.') from exc


def list_versions(path: Path) -> tuple[int | None, tuple[ImportReport, ...]]:
    if not path.exists():
        return None, ()
    try:
        with closing(_connect(path)) as db:
            db.execute('BEGIN')
            active = db.execute('SELECT version_id FROM active_version').fetchone()
            return (active[0] if active else None,
                    tuple(ImportReport(*row) for row in db.execute(f'SELECT {REPORT_FIELDS} FROM versions ORDER BY id DESC')))
    except sqlite3.Error as exc:
        raise QuoteError('Não foi possível ler o histórico da base TUSS.') from exc


def restore_version(path: Path, version: int) -> None:
    try:
        with closing(_connect(path, write=False)) as reader:
            if not reader.execute('SELECT 1 FROM versions WHERE id=?', (version,)).fetchone():
                raise QuoteError('A versão solicitada da base TUSS não existe.')
        with closing(_connect(path, write=True)) as db, db:
            _activate(db, version)
    except sqlite3.Error as exc:
        raise QuoteError('Não foi possível restaurar a versão da base TUSS.') from exc

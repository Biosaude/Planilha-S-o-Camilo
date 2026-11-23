import sqlite3
from contextlib import closing
from datetime import date
from heapq import nlargest
from pathlib import Path

from .material_matcher import material, same_brand, technical_conflicts
from .models import CatalogEntry, Product, QuoteError, TussResult
from .tuss_importer import _connect
from .validators import anvisa_key, reference_key

FIELDS = ('code, description, model, manufacturer, anvisa, starts, ends, risk, technical_name, '
          'source, sheet, row_num, model_key, anvisa_key')


def _unique_code(records):
    codes = {record.code for record in records}
    return next(iter(codes)) if len(codes) == 1 else ''


def _valid_on(record, issue_date):
    if not record.starts and not record.ends:
        return True
    return bool(issue_date and (not record.starts or record.starts <= issue_date)
                and (not record.ends or issue_date <= record.ends))


def _compatible(entry, offered):
    entry_material = material(entry.description)
    return not technical_conflicts(entry_material, offered)


def _strong_anvisa(entry, product, offered):
    if not same_brand(entry.manufacturer, product.brand):
        return False
    official = material(entry.description)
    if official.label == offered.label:
        return len(official.label.split()) >= 3
    # O subtipo ACTP permite conferir o conector Y mesmo quando o termo oficial
    # não descreve o mecanismo de rosca incluído no orçamento.
    return (official.kind == offered.kind == 'y_connector'
            and {'conector', 'y', 'actp'} <= set(official.label.split()) & set(offered.label.split())
            and ('duplo' in official.features) == ('duplo' in offered.features))


def _lookup(db, version, product, issued):
    reference = reference_key(product.reference)
    registration = anvisa_key(product.anvisa)
    offered = material(product.description)
    exact = db.execute(
        f"SELECT {FIELDS} FROM entries WHERE version_id=? AND model_key<>'' AND model_key=?",
        (version, reference),
    ).fetchall() if reference else []
    registered = db.execute(
        f"SELECT {FIELDS} FROM entries WHERE version_id=? AND anvisa_key<>'' AND anvisa_key=?",
        (version, registration),
    ).fetchall() if registration else []
    reviewed = {}
    for *fields, model, reg in exact + registered:
        entry = CatalogEntry(*fields)
        reviewed.setdefault((entry.source, entry.sheet, entry.row), entry)
    model_evidence = []
    for *fields, model, reg in exact:
        entry = CatalogEntry(*fields)
        if reg and registration and registration != reg:
            continue
        if entry.manufacturer and not same_brand(entry.manufacturer, product.brand):
            continue
        if _compatible(entry, offered) and _valid_on(entry, issued):
            model_evidence.append(entry)
    if model_evidence:
        code = _unique_code(model_evidence)
        return TussResult(code, tuple(reviewed.values()))

    registration_evidence = []
    for *fields, model, _ in registered:
        entry = CatalogEntry(*fields)
        if (not model and _valid_on(entry, issued) and _compatible(entry, offered)
                and _strong_anvisa(entry, product, offered)):
            registration_evidence.append(entry)
    registered_codes = {fields[0] for fields in registered}
    strong_code = _unique_code(registration_evidence)
    if strong_code and registered_codes == {strong_code}:
        return TussResult(strong_code, tuple(reviewed.values()))

    if not reviewed:
        if offered.kind:
            technical = db.execute(
                f"SELECT {FIELDS} FROM entries WHERE version_id=? AND device_kind<>'' AND device_kind=?",
                (version, offered.kind),
            )
        else:
            technical = db.execute(
                f'SELECT {FIELDS} FROM entries WHERE version_id=? AND label_key=?',
                (version, offered.label),
            )
        words = set(offered.label.split()) - {'de', 'da', 'para', 'com', 'do'}
        candidates = []
        for *fields, model, reg in technical:
            entry = CatalogEntry(*fields)
            if (model and reference and model != reference) or (reg and registration and reg != registration):
                continue
            if not same_brand(entry.manufacturer, product.brand):
                continue
            official = material(entry.description)
            official_words = set(official.label.split()) - {'de', 'da', 'para', 'com', 'do'}
            overlap = len(words & official_words)
            if (offered.label == official.label or
                    (overlap >= 2 and overlap * 2 >= len(words | official_words)
                     and not technical_conflicts(official, offered))):
                candidates.append((overlap, entry))
        for _, entry in nlargest(15, candidates, key=lambda candidate: candidate[0]):
            reviewed[(entry.source, entry.sheet, entry.row)] = entry
    return TussResult('', tuple(reviewed.values()))


def lookup_products(
    path: Path, products: tuple[Product, ...], issued: date | None
) -> tuple[int, tuple[TussResult, ...]]:
    if not path.is_file():
        raise QuoteError('Banco TUSS indisponível. Solicite a importação das duas partes à administração.')
    try:
        with closing(_connect(path)) as db:
            db.execute('BEGIN')
            active = db.execute('SELECT version_id FROM active_version').fetchone()
            if not active:
                raise QuoteError('Nenhuma versão TUSS ativa. Importe as duas partes da base.')
            version = active[0]
            return version, tuple(_lookup(db, version, product, issued.isoformat() if issued else '')
                                  for product in products)
    except sqlite3.Error as exc:
        raise QuoteError('Banco TUSS indisponível ou ilegível. Avise a administração.') from exc

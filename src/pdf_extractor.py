import re
from collections import defaultdict
from datetime import datetime

import pymupdf

from .models import Product, Quote, QuoteError
from .validators import MONEY_PATTERN, anvisa_key, financial_total, money, normalized, quantity, validate_upload

HEADER_WORDS = {
    'item': 'item', 'codigo': 'reference', 'referencia': 'reference', 'ref': 'reference',
    'descricao': 'description', 'produto': 'description', 'material': 'description',
    'anvisa': 'anvisa', 'reg anvisa': 'anvisa', 'registro': 'anvisa', 'validade': 'expiration',
    'marca': 'brand', 'fabricante': 'brand', 'fornecedor': 'brand',
    'quantidade': 'quantity', 'qtde': 'quantity', 'qtd': 'quantity',
    'vr unit': 'unit', 'vl unit': 'unit', 'unitario': 'unit', 'valor unitario': 'unit',
    'vr total': 'total', 'vl total': 'total', 'total': 'total', 'valor total': 'total',
}
REQUIRED = {'description', 'anvisa', 'brand', 'quantity', 'unit', 'total'}
MAX_PRODUCTS = 500
METADATA = re.compile(r'^(?:data|pag|orcamento|cliente|paciente|hospital|medico|convenio|'
                      r'endereco|cidade|estado|cep|fone|telefone|e mail|cnpj|contato|cirurgia|'
                      r'vendedor|solicitante|pedido|biosaude|observacao|observacoes|'
                      r'validade da proposta|condicoes|prazo de entrega)(?: |$)')
FOOTER = re.compile(
    r'\b(?P<amount>sub\s*total|total\s+(?:geral|produtos))\b|'
    r'\b(?P<count>itens\s+or[cç]ados)\b|\b(?P<units>total\s+de\s+unidades)\b',
    re.IGNORECASE,
)
ISSUED = re.compile(r'orçamento\s*(?:n[º°o.]?\s*)?:?\s*[\d.]+\s+de\s+'
                    r'(\d{2}/\d{2}/(?:\d{4}|\d{2}))\b', re.I)


def _lines(page):
    groups = []
    for word in sorted(page.get_text('words'), key=lambda word: (word[1], word[0])):
        midpoint = (word[1] + word[3]) / 2
        if not groups or abs(midpoint - groups[-1][0]) > 2.8:
            groups.append((midpoint, []))
        groups[-1][1].append(word)
    for _, words in groups:
        yield sorted(words, key=lambda word: word[0])


def _header(words):
    anchors = {}
    for i, word in enumerate(words):
        next_word = normalized(words[i + 1][4]) if i + 1 < len(words) else ''
        label = normalized(word[4])
        key = HEADER_WORDS.get(f'{label} {next_word}', HEADER_WORDS.get(label))
        if key:
            anchors.setdefault(key, word[0])
    if REQUIRED <= anchors.keys():
        return sorted(anchors.items(), key=lambda item: item[1])
    return None


def _columns(words, anchors):
    columns = defaultdict(list)
    positions = dict(anchors)
    for index, word in enumerate(words):
        value = word[4]
        # Identifica o preço pela borda direita mesmo quando um valor largo
        # começa na coluna anterior. O token inteiro deve ser monetário.
        if re.fullmatch(MONEY_PATTERN, value) and word[2] >= positions['unit'] - 2:
            key = 'total' if word[2] >= positions['total'] - 2 else 'unit'
        elif (value == 'R$' and index + 1 < len(words)
              and re.fullmatch(MONEY_PATTERN, words[index + 1][4])
              and words[index + 1][2] >= positions['unit'] - 2
              and 0 <= words[index + 1][0] - word[2] <= 8):
            continue
        else:
            key = anchors[0][0]
            for next_key, start in anchors[1:]:
                if word[0] < start - 2:
                    break
                key = next_key
        columns[key].append(value)
    return {key: ' '.join(parts) for key, parts in columns.items()}


def _footer_values(line, labels):
    for i, label in enumerate(labels):
        end = labels[i + 1].start() if i + 1 < len(labels) else len(line)
        value = line[label.end():end].lstrip(' .:').strip()
        kind = label.lastgroup
        if kind == 'amount':
            yield kind, money(value)
        elif kind == 'count' and re.fullmatch(r'[0-9]+', value):
            yield kind, int(value)
        elif kind == 'units' and (units := quantity(value)) is not None:
            yield kind, units
        else:
            raise QuoteError('Um número de itens ou unidades declarado no PDF ficou ilegível.')


def _product(record):
    required = REQUIRED - {'quantity'}
    if any(not record.get(key) for key in required):
        raise QuoteError('O PDF contém item com descrição, marca, ANVISA ou valores incompletos.')
    units = quantity(record.get('quantity', ''))
    if units is None or not anvisa_key(record['anvisa']) or not normalized(record['description']):
        raise QuoteError('O PDF contém quantidade, registro ANVISA ou descrição ilegível.')
    unit, total = money(record['unit']), money(record['total'])
    if financial_total(units, unit) != total:
        raise QuoteError('Quantidade × valor unitário diverge do total em um item do PDF.')
    return Product(record['description'], record['brand'], record['anvisa'], units, unit, total,
                   record.get('reference', ''))


def _append_continuation(record, columns):
    if not columns or 'item' in columns:
        raise QuoteError('Há uma continuação de tabela que não pôde ser associada a um produto.')
    for key, value in columns.items():
        if key == 'expiration':
            continue
        if key in {'reference', 'quantity', 'unit', 'total'} and record.get(key):
            raise QuoteError('Há uma continuação de tabela com valores duplicados.')
        record[key] = ' '.join(part for part in (record.get(key), value) if part)


def _parse(document):
    products, dates = [], set()
    declared = defaultdict(list)
    active = None
    record = None
    indexes = set()
    started = False
    for page in document:
        active = None
        for words in _lines(page):
            line = ' '.join(word[4] for word in words)
            label = normalized(line)
            issued = ISSUED.search(line)
            if issued:
                value = issued.group(1)
                dates.add(datetime.strptime(value, '%d/%m/%Y' if len(value) == 10 else '%d/%m/%y').date())
            header = _header(words)
            if header:
                active = header
                started = True
                continue
            if started and FOOTER.match(line):
                if record:
                    products.append(_product(record))
                    record = None
                for key, value in _footer_values(line, list(FOOTER.finditer(line))):
                    declared[key].append(value)
                active = None
                continue
            if not active or not label or METADATA.match(label):
                if not active and started and re.search(r'\b[0-9]{11}\b', line):
                    if len(re.findall(MONEY_PATTERN, line)) >= 2:
                        raise QuoteError('Um produto está fora de uma tabela com cabeçalho reconhecível.')
                continue
            columns = _columns(words, active)
            numbered = any(key == 'item' for key, _ in active)
            starts_row = bool(columns.get('item')) if numbered else bool(
                columns.get('reference') or (not record or record.get('total')) and columns.get('quantity')
            )
            if starts_row:
                if len(products) + bool(record) >= MAX_PRODUCTS:
                    raise QuoteError('O orçamento excede o limite de 500 produtos.')
                if record:
                    products.append(_product(record))
                index = columns.get('item')
                if index and (not index.isdecimal() or index in indexes):
                    raise QuoteError('A numeração dos produtos do PDF é ambígua.')
                if index:
                    indexes.add(index)
                record = columns
            elif record:
                _append_continuation(record, columns)
            else:
                raise QuoteError('Há uma linha de produto sem os campos esperados no PDF.')
    if record:
        products.append(_product(record))
    if not products:
        raise QuoteError('Tabela VS|OPME não localizada. Envie um PDF pesquisável com os cabeçalhos do orçamento.')
    if indexes and (len(indexes) != len(products) or {int(i) for i in indexes} != set(range(1, len(products) + 1))):
        raise QuoteError('A numeração indica itens ausentes ou duplicados no PDF.')
    if any(count != len(products) for count in declared['count']):
        raise QuoteError('A quantidade de itens extraídos diverge do total de itens do PDF.')
    if any(units != sum(product.quantity for product in products) for units in declared['units']):
        raise QuoteError('A soma das quantidades extraídas diverge do total de unidades do PDF.')
    if any(total != sum(product.total for product in products) for total in declared['amount']):
        raise QuoteError('O total do orçamento diverge da soma dos produtos extraídos.')
    if len(dates) > 1:
        raise QuoteError('O PDF contém mais de uma data de emissão de orçamento.')
    return Quote(tuple(products), next(iter(dates), None))


def extract_quote(payload: bytes, name: str) -> Quote:
    validate_upload(payload, name, '.pdf')
    if not payload.startswith(b'%PDF-'):
        raise QuoteError('O arquivo enviado não tem a estrutura de um PDF.')
    try:
        with pymupdf.open(stream=payload, filetype='pdf') as document:
            if document.needs_pass or len(document) > 100 or document.is_repaired:
                raise QuoteError('PDF protegido, corrompido ou acima do limite de 100 páginas.')
            return _parse(document)
    except QuoteError:
        raise
    except (RuntimeError, ValueError, OverflowError) as exc:
        raise QuoteError('Não foi possível interpretar o PDF íntegro no padrão VS|OPME.') from exc

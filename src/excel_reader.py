from .models import HospitalRow, HospitalSheet, QuoteError
from .validators import anvisa_key, normalized, open_xlsx, quantity, text_value

TARGETS = {
    2: {'tuss', 'codigo tuss', 'cod tuss', 'codigo do tuss'},
    4: {'descricao', 'descricao material', 'descricao do material', 'descricao do produto',
        'descricao material fornecedor', 'descricao do material fornecedor', 'descricao cotada', 'descricao fornecedor', 'material cotado', 'descricao do item'},
    5: {'fornecedor', 'marca', 'fornecedor marca', 'marca fornecedor', 'fabricante',
        'fabricante fornecedor', 'marca fabricante', 'fabricante marca', 'marca do produto'},
    6: {'anvisa', 'registro anvisa', 'reg anvisa', 'anvisa referencia', 'registro na anvisa', 'numero anvisa'},
    7: {'valor unitario', 'vl unitario', 'vlr unitario', 'preco unitario', 'valor unitario r',
        'unitario', 'valor unit'},
    8: {'valor total', 'vl total', 'vlr total', 'preco total', 'valor total r', 'total'},
}
REQUESTED = {'material solicitado', 'descricao solicitada', 'descricao hospital',
             'descricao do material solicitado', 'descricao do material pedido medico', 'item solicitado', 'produto solicitado',
             'material', 'produto', 'especificacao', 'descricao', 'descricao padronizada'}
QUANTITY = {'quantidade', 'qtd', 'qtde', 'quantidade solicitada', 'qtd solicitada', 'quant'}
REFERENCE = {'referencia', 'referencia tecnica', 'ref', 'modelo', 'referencia modelo',
             'codigo referencia', 'codigo do produto', 'codigo material'}
BRAND = TARGETS[5]
ANVISA = TARGETS[6]
MAX_ROWS = 20_000
MAX_COLUMNS = 256


def _label(value):
    label = normalized(value)
    return label.removesuffix(' r') if label.endswith(' r') else label


def _header_candidates(workbook):
    for sheet in workbook.worksheets:
        if sheet.sheet_state != 'visible':
            continue
        for cells in sheet.iter_rows(
            min_row=1, max_row=min(sheet.max_row, 150), max_col=min(sheet.max_column, MAX_COLUMNS)
        ):
            labels = {cell.column: _label(cell.value) for cell in cells if cell.value is not None}
            if not all(labels.get(column) in aliases for column, aliases in TARGETS.items()):
                continue
            other = {column: label for column, label in labels.items() if column not in TARGETS}
            descriptors = [column for column, label in other.items() if label in REQUESTED]
            if len(descriptors) > 1:
                raise QuoteError('Há mais de uma coluna de descrição solicitada no modelo.')
            yield sheet, cells[0].row, descriptors[0] if descriptors else 4, other


def _single_column(labels, aliases):
    matching = [column for column, label in labels.items() if label in aliases]
    if len(matching) > 1:
        raise QuoteError('O modelo contém colunas de entrada duplicadas no cabeçalho.')
    return matching[0] if matching else None


def read_hospital(payload: bytes, name: str) -> HospitalSheet:
    workbook = open_xlsx(payload, name)
    try:
        candidates = list(_header_candidates(workbook))
        if len(candidates) != 1:
            raise QuoteError('Modelo incompatível: confirme uma única tabela com TUSS em B, '
                             'descrição em D, marca em E, ANVISA em F e valores em G/H.')
        sheet, header, description, columns = candidates[0]
        if sheet.protection.sheet:
            raise QuoteError('A aba de cotação está protegida contra alterações.')
        if sheet.max_row > MAX_ROWS or sheet.max_column > MAX_COLUMNS:
            raise QuoteError('A aba de cotação excede os limites de linhas ou colunas.')
        count_col = _single_column(columns, QUANTITY)
        ref_col = _single_column(columns, REFERENCE)
        brand_col = _single_column(columns, BRAND)
        anvisa_col = _single_column(columns, ANVISA)
        rows = []
        for row in range(header + 1, sheet.max_row + 1):
            cell = sheet.cell(row, description)
            requested = text_value(cell.value)
            if cell.data_type in {'f', 'e'} or not normalized(requested):
                continue
            if normalized(requested) in {'total', 'subtotal', 'total geral', 'observacoes',
                                         'descricao', 'material solicitado'}:
                continue
            if requested.isnumeric() or normalized(requested).startswith(
                ('observacao ', 'observacoes ', 'assinatura ', 'validade da proposta ')
            ):
                continue
            units = quantity(sheet.cell(row, count_col).value) if count_col else None
            if count_col and units is None:
                continue
            reference = sheet.cell(row, ref_col) if ref_col else None
            brand = sheet.cell(row, brand_col) if brand_col else None
            anvisa = sheet.cell(row, anvisa_col) if anvisa_col else None
            rows.append(HospitalRow(
                row, requested, units,
                text_value(reference.value) if reference and reference.data_type != 'f' else '',
                text_value(brand.value) if brand and brand.data_type != 'f' else '',
                text_value(anvisa.value) if anvisa and anvisa_key(text_value(anvisa.value)) else '',
            ))
        if not rows:
            raise QuoteError('Nenhuma linha de material legível foi localizada na tabela de cotação.')
        return HospitalSheet(sheet.title, count_col, tuple(rows))
    finally:
        workbook.close()

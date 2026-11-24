import os
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from conftest import HEADERS
from src.excel_reader import read_hospital
from src.excel_writer import export_workbook

from src.pdf_extractor import _columns, _product, extract_quote


def _word(x0, x1, value):
    return (x0, 0, x1, 8, value, 0, 0, 0)


def test_vsopme_right_aligned_prices_do_not_fall_into_quantity_column():
    # Positions reproduce the VS|OPME report layout (quote 73.582).
    anchors = [
        ('item', 25.2), ('reference', 46.2), ('description', 113.4),
        ('anvisa', 252.0), ('expiration', 319.2), ('brand', 357.0),
        ('quantity', 428.5), ('unit', 466.3), ('total', 529.3),
    ]
    words = [
        _word(33.6, 42.0, '18'), _word(46.2, 67.2, '35012'),
        _word(113.4, 126.0, 'CAT'), _word(130.2, 151.2, 'LITOT'),
        _word(252.0, 298.2, '10256400086'),
        _word(319.2, 352.8, '21/07/35'),
        _word(357.0, 411.7, 'SPECTRUMEDICS'),
        _word(441.1, 445.3, '2'),
        _word(462.1, 499.9, '60.000,00'),
        _word(520.9, 562.9, '120.000,00'),
    ]
    columns = _columns(words, anchors)
    assert columns['quantity'] == '2'
    assert columns['unit'] == '60.000,00'
    assert columns['total'] == '120.000,00'
    product = _product(columns)
    assert product.unit == Decimal('60000.00')
    assert product.total == Decimal('120000.00')


def test_vsopme_small_prices_still_parse_correctly():
    anchors = [('quantity', 428.5), ('unit', 466.3), ('total', 529.3)]
    words = [
        _word(441.1, 445.3, '1'),
        _word(474.7, 499.9, '600,00'),
        _word(537.7, 562.9, '600,00'),
    ]
    assert _columns(words, anchors) == {
        'quantity': '1', 'unit': '600,00', 'total': '600,00',
    }


def test_monetario_em_coluna_anterior_exige_token_completo():
    anchors = [('brand', 357), ('quantity', 428.5), ('unit', 466.3), ('total', 529.3)]
    words = [
        _word(357, 385, 'MODELO'),
        _word(389, 410, '1,25'),
        _word(411, 424, 'R$'),
        _word(427, 499.9, '12.345.678,90'),
        _word(440, 445, '2'),
        _word(515, 562.9, '24.691.357,80'),
    ]
    assert _columns(words, anchors) == {
        'brand': 'MODELO 1,25', 'quantity': '2', 'unit': '12.345.678,90', 'total': '24.691.357,80',
    }
    words[3] = _word(427, 499.9, 'X12.345.678,90')
    assert 'unit' not in _columns(words, anchors)


def test_orcamento_73582_original():
    path = os.environ.get('BIOSAUDE_TEST_PDF_73582')
    if not path:
        if os.environ.get('BIOSAUDE_REQUIRE_REFERENCE') == '1':
            pytest.fail('Defina o caminho privado do orçamento nº 73.582.')
        pytest.skip('Defina BIOSAUDE_TEST_PDF_73582 para validar o orçamento original.')
    pdf = Path(path)
    quote = extract_quote(pdf.read_bytes(), pdf.name)
    assert len(quote.products) == 20
    assert sum(item.quantity for item in quote.products) == 27
    assert sum(item.unit for item in quote.products) == Decimal('205364.37')
    assert sum(item.total for item in quote.products) == Decimal('311964.37')
    assert max(item.total for item in quote.products) == Decimal('120000.00')
    # O Excel deste teste é montado em memória. O PDF não entra no repositório.
    book = Workbook()
    sheet = book.active
    sheet.append(HEADERS)
    assignments = []
    for row, product in enumerate(quote.products, 2):
        sheet.append([product.quantity, None, product.description])
        sheet[f'H{row}'] = f'=A{row}*G{row}'
        assignments.append((row, product, ''))
    sheet['G22'] = '=SUM(G2:G21)'
    sheet['H22'] = '=SUM(H2:H21)'
    original = BytesIO()
    book.save(original)
    source = original.getvalue(), 'cotacao.xlsx'
    exported = export_workbook(*source, read_hospital(*source), assignments)
    cached = load_workbook(BytesIO(exported), data_only=True).active
    assert Decimal(str(cached['G22'].value)) == Decimal('205364.37')
    assert Decimal(str(cached['H22'].value)) == Decimal('311964.37')
    assert cached['H19'].value == 120000

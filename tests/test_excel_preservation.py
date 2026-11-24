from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, PatternFill, Side

from src.excel_reader import read_hospital
from src.excel_writer import export_workbook
from src.models import QuoteError
from src.pdf_extractor import extract_quote


def test_preserva_estilos_formulas_impressao_e_celulas(excel, pdf):
    hospital = read_hospital(*excel)
    first, second = extract_quote(*pdf).products
    result = export_workbook(*excel, hospital, [(4, first, '00000123'), (3, second, '')])
    base, new = [load_workbook(BytesIO(payload)) for payload in (excel[0], result)]
    assert new.sheetnames == base.sheetnames
    a, b = base.active, new.active
    assert b['B3'].value is None
    assert b['E5'].value is None
    assert b['H3'].value == '=A3*G3'
    assert b['G3'].value == 480 and b['H4'].value == 200
    assert b['B4'].value == '00000123' and b['F4'].value == '01234567890'
    assert b['H6'].value == '=SUM(H3:H5)' and new['Outra aba']['B4'].value == '=2*7'
    assert b['D5'].value == 'não alterar' and b['B5'].value == 'keep'
    assert a['G4'].style_id == b['G4'].style_id
    assert a.merged_cells == b.merged_cells
    assert a.column_dimensions['C'].width == b.column_dimensions['C'].width
    assert a.row_dimensions[4].height == b.row_dimensions[4].height
    assert a.print_area == b.print_area and a.page_setup == b.page_setup and a.print_options == b.print_options
    assert a.oddFooter.center.text == b.oddFooter.center.text
    with ZipFile(BytesIO(excel[0])) as original, ZipFile(BytesIO(result)) as modified:
        assert {part for part in original.namelist() if original.read(part) != modified.read(part)} == {
            'xl/worksheets/sheet1.xml', 'xl/workbook.xml',
        }


def test_planilha_incompativel_ou_corrompida(excel):
    with pytest.raises(QuoteError):
        read_hospital(b'broken', 'cotacao.xlsx')
    book = load_workbook(BytesIO(excel[0]))
    book.active['G2'] = 'Coluna completamente diferente'
    buf = BytesIO()
    book.save(buf)
    with pytest.raises(QuoteError, match='Modelo incompatível'):
        read_hospital(buf.getvalue(), excel[1])


def test_excel_nao_substitui_formula_na_area_autorizada(excel, pdf):
    book = load_workbook(BytesIO(excel[0]))
    book.active['D4'] = '=2+5'
    buf = BytesIO()
    book.save(buf)
    corrupted = (buf.getvalue(), excel[1])
    hospital = read_hospital(*corrupted)
    first = extract_quote(*pdf).products[0]
    with pytest.raises(QuoteError, match='fórmula'):
        export_workbook(*corrupted, hospital, [(4, first, '')])



@pytest.mark.parametrize(('brand', 'expected'), [
    ('BOSTON', 'BOSTON - BIOSAUDE'),
    ('EPTCA - Biosaúde', 'EPTCA - BIOSAUDE'),
    ('SCW MEDICATH - Biosaude - BIOSAÚDE ', 'SCW MEDICATH - BIOSAUDE'),
    ('MEDTRONIC – BIOSAUDE', 'MEDTRONIC - BIOSAUDE'),
    ('ABBOTT Biosaúde', 'ABBOTT - BIOSAUDE'),
    ('GORE - Biosaúde Brasil', 'GORE - Biosaúde Brasil - BIOSAUDE'),
    ('Biosaúde', 'BIOSAUDE'),
    ('', None),
])
def test_sufixo_apenas_na_exportacao(excel, pdf, brand, expected):
    original = replace(extract_quote(*pdf).products[0], brand=brand)
    result = export_workbook(*excel, read_hospital(*excel), [(4, original, '')])
    sheet = load_workbook(BytesIO(result)).active
    assert sheet['E4'].value == expected
    assert sheet['E3'].value is None and sheet['E5'].value is None
    assert original.brand == brand


@pytest.mark.parametrize(('tuss', 'anvisa', 'expected_tuss', 'expected_anvisa'), [
    ('70771234', '10987654321', 70771234, 10987654321),
    ('00000123', '01234567890', '00000123', '01234567890'),
    ('AB12345', 'ANV-001ABC', 'AB12345', 'ANV-001ABC'),
    ('1234567890123456', '123456789012', '1234567890123456', '123456789012'),
])
def test_tipos_numericos_e_identificadores_exatos(excel, pdf, tuss, anvisa, expected_tuss, expected_anvisa):
    item = replace(extract_quote(*pdf).products[0], anvisa=anvisa,
                   unit=Decimal('123456.78'), total=Decimal('123456.78'))
    book = load_workbook(BytesIO(excel[0]))
    sheet = book.active
    sheet['F4'].fill = PatternFill('solid', fgColor='FEDCBA')
    sheet['F4'].border = Border(bottom=Side(style='thin', color='000000'))
    sheet['F4'].alignment = Alignment(horizontal='right')
    sheet['G4'].number_format = '#,##0.00'
    buf = BytesIO()
    book.save(buf)
    source = (buf.getvalue(), excel[1])
    result = export_workbook(*source, read_hospital(*source), [(4, item, tuss)])
    target = load_workbook(BytesIO(result)).active
    for addr, value in {'B4': expected_tuss, 'F4': expected_anvisa, 'G4': 123456.78, 'H4': 123456.78}.items():
        assert target[addr].value == value
        assert target[addr].data_type == ('s' if isinstance(value, str) else 'n')
        assert target[addr].style_id == sheet[addr].style_id


@pytest.mark.parametrize('calc_mode', ['manual', 'absent'])
def test_cache_total_linha_e_somas_com_recalculo_ao_abrir(excel, pdf, calc_mode):
    book = load_workbook(BytesIO(excel[0]))
    book.active['H3'] = '=ROUND($G3*$A3,2)'
    book.active['H5'] = '=A5*G5'
    book.active['G5'] = 20
    book.active['G6'] = '=SUM($G$3:$G$5)'
    if calc_mode == 'manual':
        book.calculation.calcMode = 'manual'
        book.calculation.calcId = 142
    else:
        book.calculation = None
    buf = BytesIO()
    book.save(buf)
    # Simula valores obsoletos no cache, como em um arquivo salvo pelo Excel.
    with ZipFile(buf) as before:
        saved = BytesIO()
        with ZipFile(saved, 'w') as after:
            for name in before.namelist():
                content = before.read(name)
                if name == 'xl/worksheets/sheet1.xml':
                    content = content.replace(b'<f>SUM(H3:H5)</f><v></v>', b'<f>SUM(H3:H5)</f><v>999</v>')
                after.writestr(name, content)
    source = saved.getvalue(), excel[1]
    assert load_workbook(BytesIO(source[0]), data_only=True).active['H6'].value == 999
    first, second = extract_quote(*pdf).products
    result = export_workbook(*source, read_hospital(*source), [(4, first, ''), (3, second, '')])
    exported = load_workbook(BytesIO(result))
    flags = exported.calculation
    assert (flags.calcMode, flags.fullCalcOnLoad, flags.forceFullCalc, flags.calcCompleted) == ('auto', True, True, False)
    if calc_mode == 'manual':
        assert flags.calcId == 142
    for addr in ('H3', 'H5', 'G6', 'H6'):
        assert exported.active[addr].value == book.active[addr].value
    cached = load_workbook(BytesIO(result), data_only=True).active
    assert (cached['G6'].value, cached['H6'].value, cached['H3'].value) == (700, 1660, 1440)
    assert cached['H5'].value is None  # A linha não cotada não é regravada.

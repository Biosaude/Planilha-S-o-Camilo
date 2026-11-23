from io import BytesIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

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
        assert [part for part in original.namelist() if original.read(part) != modified.read(part)] == ['xl/worksheets/sheet1.xml']


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

from io import BytesIO

import pymupdf
import pytest
from openpyxl import Workbook
from openpyxl.styles import Font

from src.tuss_importer import FILENAMES, import_bases

HEADERS = ['Qtd', 'TUSS', 'Material solicitado', 'Descrição do material', 'Marca', 'ANVISA',
           'Valor unitário', 'Valor total', 'Referência']


def _xlsx(workbook):
    binary = BytesIO()
    workbook.save(binary)
    return binary.getvalue()


def make_catalog(records):
    book = Workbook()
    book.active.append(['Código do Termo', 'Termo', 'Fabricante', 'Registro Anvisa',
                        'Modelo', 'Início de vigência', 'Fim de vigência', 'Classe de risco', 'Nome técnico'])
    for record in records:
        book.active.append(record)
    return _xlsx(book)


@pytest.fixture
def excel():
    book = Workbook()
    sheet = book.active
    sheet.title = 'Cotação'
    sheet.merge_cells('A1:I1')
    sheet['A1'] = 'Modelo sintético'
    sheet.append(HEADERS)
    sheet.append([3, None, 'Conector Y rosqueável', None, None, None, None, '=A3*G3'])
    sheet.append([1, None, 'Introdutor radial 6FR', None, None, None, None, None, 'RAD6'])
    sheet.append([1, 'keep', 'Cateter 10FR', 'não alterar'])
    sheet['G6'] = '=SUM(G3:G5)'
    sheet['H6'] = '=SUM(H3:H5)'
    sheet['G4'].font = Font(bold=True, color='FF2233')
    sheet.column_dimensions['C'].width = 55
    sheet.row_dimensions[4].height = 27
    sheet.page_setup.orientation = "landscape"
    sheet.print_options.horizontalCentered = True
    sheet.print_area = 'A1:I6'
    sheet.oddFooter.center.text = 'Página &P'
    book.create_sheet('Outra aba')['B4'] = '=2*7'
    return _xlsx(book), 'cotacao.xlsx'


def make_pdf(*, corrupt_total=False, partial=False, wrapped=True,
             declared_items='2', declared_units='4', declared_total='1.640,00'):
    columns = [15, 42, 103, 275, 340, 389, 469, 510]
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((15, 20), 'Orçamento Nº: 10.001 de 18/11/26', fontsize=8)
        page.insert_text((15, 35), 'Paciente: Exemplo de teste', fontsize=8)
        lines = [
            ['Item', 'Código', 'Descrição do produto', 'Reg.ANVISA', 'Marca', 'Qtde', 'Vr.unit.', 'Vr.total'],
            ['1', 'RAD6', 'INTRODUTOR RADIAL 6FR', '01234567890', 'MODELO A', '1', '200,00', '201,00' if corrupt_total else '200,00'],
            ['2', 'Y1234', 'CONECT Y ACTP', '10987654321', 'MODELO B', '3', '480,00', '' if partial else '1.440,00'],
        ]
        for i, row in enumerate(lines):
            for x, value in zip(columns, row, strict=True):
                if value:
                    page.insert_text((x, 85 + 13 * i), value, fontsize=8)
        if wrapped:
            page.insert_text((103, 124), 'ROSQUEAV', fontsize=8)
        page.insert_text((15, 150), f'Itens orçados: {declared_items}', fontsize=8)
        page.insert_text((15, 165), f'Total de unidades: {declared_units}', fontsize=8)
        page.insert_text((460, 165), f'Total geral: {declared_total}', fontsize=8)
        return doc.tobytes(), 'orcamento.pdf'


@pytest.fixture
def pdf():
    return make_pdf()


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / 'tuss.sqlite3'
    first = make_catalog([['00000123', 'INTRODUTOR RADIAL 6FR', 'MODELO A', '01234567890', 'RAD6']])
    second = make_catalog([['00000456', 'CONECTOR Y PARA ACTP', 'MODELO B', '10987654321']])
    import_bases(path, (first, FILENAMES[0]), (second, FILENAMES[1]), 'Catalogo sintético')
    return path

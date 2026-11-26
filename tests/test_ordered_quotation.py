import os
from dataclasses import replace
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from src.excel_reader import read_hospital
from src.material_matcher import match_products
from src.models import HospitalRow, HospitalSheet, Product
from src.pdf_extractor import extract_quote
from src.tuss_importer import import_bases
from src.workflow import _match_quotation, analyze, generate


def test_complete_ordered_quotation():
    rows = tuple(HospitalRow(i + 9, f'Pedido {i}', Decimal(2 if i in (15, 21) else 1)) for i in range(24))
    hospital = HospitalSheet('Cotação', 1, rows)
    products = tuple(Product(f'Material {i}', 'MARCA', '12345678901', row.quantity,
                             Decimal(10), row.quantity * 10, str(i)) for i, row in enumerate(rows))
    matches = _match_quotation(products, hospital)
    assert tuple(match.row for match in matches) == rows
    swapped = (products[15], *products[1:15], products[0], *products[16:])
    for altered in (products[:-1], swapped):
        assert _match_quotation(altered, hospital) == match_products(altered, rows)
    unknown = (replace(rows[0], quantity=None),) + rows[1:]
    assert _match_quotation(products, replace(hospital, rows=unknown)) == match_products(products, unknown)


@pytest.mark.parametrize('invalid_quantity', [None, 'pendente'])
def test_quantidade_ilegivel_no_excel_impede_correspondencia_por_ordem(excel, pdf, invalid_quantity):
    workbook = load_workbook(BytesIO(excel[0]))
    sheet = workbook.active
    sheet['A3'], sheet['A4'] = 1, 3
    sheet['A5'] = invalid_quantity
    updated = BytesIO()
    workbook.save(updated)
    hospital = read_hospital(updated.getvalue(), excel[1])
    products = extract_quote(*pdf).products
    assert len(hospital.rows) == len(products)
    assert tuple(row.quantity for row in hospital.rows) == tuple(item.quantity for item in products)
    assert hospital.has_unreadable_quantities
    matches = _match_quotation(products, hospital)
    assert matches == match_products(products, hospital.rows)
    assert any(match.row is None for match in matches)


def test_orcamento_73617_original_exporta_sem_revisao(tmp_path):
    variables = ('BIOSAUDE_TEST_EXCEL_73617', 'BIOSAUDE_TEST_PDF_73617', 'BIOSAUDE_TEST_TUSS_1', 'BIOSAUDE_TEST_TUSS_2')
    if not all(os.environ.get(key) for key in variables):
        if os.environ.get('BIOSAUDE_REQUIRE_73617') == '1':
            pytest.fail('Defina os caminhos privados do Excel, do PDF nº 73.617 e das duas bases TUSS.')
        pytest.skip('Defina os caminhos privados dos arquivos do orçamento nº 73.617 e das bases TUSS.')

    def uploaded(key):
        path = Path(os.environ[key])
        return path.read_bytes(), path.name

    excel, pdf, part1, part2 = (uploaded(key) for key in variables)
    db = tmp_path / 'tuss.sqlite3'
    import_bases(db, part1, part2, 'Referência 73.617')
    audit = tmp_path / 'audit.sqlite3'
    analysis = analyze(excel, pdf, db)

    products = analysis.quote.products
    assert len(products) == len(analysis.hospital.rows) == len(analysis.matches) == 24
    assert sum(product.quantity for product in products) == 26
    assert tuple(match.row.number for match in analysis.matches) == tuple(range(9, 33))
    assert tuple(product.quantity for product in products) == tuple(row.quantity for row in analysis.hospital.rows)
    assert sum(product.unit for product in products) == Decimal('189402.00')
    assert sum(product.total for product in products) == Decimal('192022.00')
    output = generate(excel, analysis, {}, audit, 'teste', 'operador')
    assert not audit.exists()

    original = load_workbook(BytesIO(excel[0]))
    exported = load_workbook(BytesIO(output))
    cached = load_workbook(BytesIO(output), data_only=True)
    old_sheet = original[analysis.hospital.title]
    new_sheet = exported[analysis.hospital.title]
    values = cached[analysis.hospital.title]
    for row, product, tuss in zip(analysis.hospital.rows, products, analysis.tuss, strict=True):
        number = row.number
        expected_code = int(tuss.code) if tuss.code.isascii() and tuss.code.isdigit() and len(tuss.code) <= 11 and not tuss.code.startswith('0') else tuss.code or None
        assert new_sheet[f'B{number}'].value == expected_code
        assert new_sheet[f'D{number}'].value == product.description
        assert new_sheet[f'E{number}'].value == f'{product.brand} - BIOSAUDE'
        assert new_sheet[f'F{number}'].value == ' - '.join(filter(None, (product.anvisa, product.reference)))
        assert new_sheet[f'F{number}'].data_type == 's'
        assert Decimal(str(values[f'G{number}'].value)) == product.unit
        assert Decimal(str(values[f'H{number}'].value)) == product.total
        for column in 'BDEFGH':
            assert old_sheet[f'{column}{number}'].style_id == new_sheet[f'{column}{number}'].style_id
    for address, expected in (('G33', 189402), ('H33', 192022)):
        assert new_sheet[address].data_type == 'f'
        assert new_sheet[address].value == old_sheet[address].value
        assert values[address].value == expected
    assert exported.calculation.calcMode == 'auto'
    assert exported.calculation.fullCalcOnLoad
    assert old_sheet.merged_cells == new_sheet.merged_cells
    assert old_sheet.print_area == new_sheet.print_area
    with ZipFile(BytesIO(excel[0])) as before, ZipFile(BytesIO(output)) as after:
        assert before.namelist() == after.namelist()
        assert {part for part in before.namelist() if before.read(part) != after.read(part)} == {
            'xl/workbook.xml', 'xl/worksheets/sheet1.xml',
        }

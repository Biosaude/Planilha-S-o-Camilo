import os
import sqlite3
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from conftest import make_pdf
from src.models import QuoteError
from src.tuss_importer import FILENAMES, import_bases
from src.workflow import analyze, generate


def _file(path):
    return path.read_bytes(), path.name


def test_fluxo_completo_sintetico(excel, pdf, catalog, tmp_path):
    analysis = analyze(excel, pdf, catalog)
    output = generate(excel, analysis, {}, tmp_path / 'audit.sqlite', 'test', 'operador')
    sheet = load_workbook(BytesIO(output)).active
    assert (sheet['B4'].value, sheet['B3'].value) == ('00000123', '00000456')
    assert sheet['E4'].value == 'MODELO A - BIOSAUDE'
    assert analysis.quote.products[0].brand == 'MODELO A'


@pytest.mark.parametrize(('anvisa', 'reference', 'expected'), [
    ('10349000875', 'AFAPRO28', '10349000875 - AFAPRO28'),
    ('01234567890', '000.00AB', '01234567890 - 000.00AB'),
    ('', '000.00AB', '000.00AB'),
    ('10987654321', '', '10987654321'),
])
def test_coluna_f_do_pdf_ao_excel(excel, catalog, tmp_path, anvisa, reference, expected):
    pdf = make_pdf(second_anvisa=anvisa, second_reference=reference)
    analysis = analyze(excel, pdf, catalog)
    product = analysis.quote.products[1]
    assert (product.anvisa, product.reference) == (anvisa, reference)
    assert analysis.matches[1].row.number == 3
    output = generate(excel, analysis, {}, tmp_path / 'audit.sqlite', 'test', 'operador')
    sheet = load_workbook(BytesIO(output)).active
    assert (sheet['F3'].value, sheet['F3'].data_type) == (expected, 's')
    assert sheet['H3'].value == '=A3*G3'
    assert sheet['H6'].value == '=SUM(H3:H5)'
    assert sheet.parent.calculation.calcMode == 'auto'
    cached = load_workbook(BytesIO(output), data_only=True).active
    assert (cached['G6'].value, cached['H6'].value) == (680, 1640)


def test_orcamento_73358_com_arquivos_originais(tmp_path):
    variables = ('BIOSAUDE_TEST_EXCEL', 'BIOSAUDE_TEST_PDF', 'BIOSAUDE_TEST_TUSS_1', 'BIOSAUDE_TEST_TUSS_2')
    paths = [os.environ.get(name) for name in variables]
    if not all(paths):
        if os.environ.get('BIOSAUDE_REQUIRE_REFERENCE') == '1':
            pytest.fail('Defina os quatro caminhos para executar o caso obrigatório nº 73.358.')
        pytest.skip('Defina os caminhos privados dos quatro originais para testar o orçamento nº 73.358.')
    excel, pdf, part1, part2 = map(_file, map(Path, paths))
    assert (part1[1], part2[1]) == FILENAMES
    db, audit = tmp_path / 'tuss.sqlite3', tmp_path / 'audit.sqlite3'
    report = import_bases(db, part1, part2, 'Referência 73.358')
    assert (report.count1, report.count2) == (35086, 12193)
    analysis = analyze(excel, pdf, db)
    assert analysis.quote.issued == date(2026, 11, 18)
    expected_rows = (17, 10, 11, 25, 26, 22)
    expected_products = [
        ('M00146154B0', '10341350515', 1, 550, 550, '70771308'),
        ('42.10.20100', '81506640009', 1, 200, 200, ''),
        ('834905', '10332200063', 1, 120, 120, ''),
        ('833601', '10332200050', 6, 125, 750, ''),
        ('832901', '10332200049', 3, 480, 1440, '78248175'),
        ('H7493893104J0', '10341350351', 1, 420, 420, '71332715'),
    ]
    assert [match.row.number if match.row else None for match in analysis.matches] == [None, 10, 11, 25, 26, None]
    assert [bool(result.candidates) for result in analysis.tuss] == [True, False, True, True, True, True]
    assert len(analysis.quote.products) == len(expected_products)
    with pytest.raises(QuoteError, match='Conclua a revisão'):
        generate(excel, analysis, {}, audit, 'operador-teste', 'operador')
    # As duas linhas vêm do resultado de referência fornecido; o sistema registra a confirmação manual.
    decisions = {0: expected_rows[0], 5: expected_rows[5]}
    result = generate(excel, analysis, decisions, audit, 'operador-teste', 'operador')
    assert generate(excel, analysis, decisions, audit, 'operador-teste', 'operador') == result
    sheet = load_workbook(BytesIO(result)).active
    assert sum(product.total for product in analysis.quote.products) == Decimal('3480.00')
    for row, product, expected in zip(expected_rows, analysis.quote.products, expected_products, strict=True):
        ref, anvisa, units, unit, total, code = expected
        assert (product.reference, product.anvisa, product.quantity, product.unit, product.total) == (ref, anvisa, units, unit, total)
        assert [sheet.cell(row, c).value for c in (2, 4, 5, 6, 7, 8)] == [
            int(code) if code else None, product.description, f'{product.brand} - BIOSAUDE', f'{anvisa} - {ref}', unit, total,
        ]
    assert sheet['G29'].value == '=SUM(G9:G28)' and sheet['H29'].value == '=SUM(H9:H28)'
    cached = load_workbook(BytesIO(result), data_only=True).active
    assert cached['G29'].value == sum(product.unit for product in analysis.quote.products)
    assert cached['H29'].value == 3480
    assert sheet.parent.calculation.calcMode == 'auto'
    with ZipFile(BytesIO(excel[0])) as before, ZipFile(BytesIO(result)) as after:
        assert before.namelist() == after.namelist()
        assert {part for part in before.namelist() if before.read(part) != after.read(part)} == {
            'xl/worksheets/sheet1.xml', 'xl/workbook.xml',
        }
    with sqlite3.connect(audit) as audit_db:
        assert audit_db.execute('SELECT item,hospital_row,action FROM decisions ORDER BY item').fetchall() == [
            (1, 17, 'confirmado_manual'), (6, 22, 'confirmado_manual'),
        ]

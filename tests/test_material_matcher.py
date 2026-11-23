from dataclasses import replace
from decimal import Decimal

from src.excel_reader import read_hospital
from src.material_matcher import match_products
from src.models import HospitalRow
from src.pdf_extractor import extract_quote


def test_associa_por_criterios_tecnicos_fora_de_ordem(excel, pdf):
    matches = match_products(extract_quote(*pdf).products, read_hospital(*excel).rows)
    assert [match.row.number for match in matches] == [4, 3]


def test_ambiguidades_disputam_mesma_linha(excel, pdf):
    products = extract_quote(*pdf).products
    rows = read_hospital(*excel).rows
    duplicate = replace(rows[1], number=99)
    assert match_products(products, (*rows, duplicate))[0].row is None
    assert all(match.row is None for match in match_products((products[0], products[0]), rows))


def test_referencia_nao_supera_conflitos(excel, pdf):
    product = extract_quote(*pdf).products[0]
    rows = (HospitalRow(2, 'Introdutor femoral 8 FR',
                        Decimal(1), product.reference),)
    match = match_products((product,), rows)[0]
    assert match.row is None and match.candidates == rows


def test_fio_guia_diametro_e_rigidez_exigem_evidencia(pdf):
    product = replace(extract_quote(*pdf).products[0], reference='', description='FIO GUIA 0,035X260')
    rows = (HospitalRow(10, 'FIO GUIA STIFF 0.35 IN. 260 CM', Decimal(1)),
            HospitalRow(11, 'FIO GUIA SOFT 0,035 IN. 260 CM', Decimal(1)))
    match = match_products((product,), rows)[0]
    assert match.row is None and len(match.candidates) == 2

from dataclasses import replace
from datetime import date

import pytest

from conftest import make_catalog
from src.models import QuoteError
from src.pdf_extractor import extract_quote
from src.tuss_importer import FILENAMES, import_bases, list_versions, restore_version
from src.tuss_repository import lookup_products


def test_partes_origem_e_niveis(catalog, pdf):
    quote = extract_quote(*pdf)
    version, results = lookup_products(catalog, quote.products, quote.issued)
    assert version == 1
    assert [result.code for result in results] == ['00000123', '00000456']
    assert [result.candidates[0].source for result in results] == [1, 2]
    assert list_versions(catalog)[1][0].count2 == 1


def test_mesmo_anvisa_multiplos_modelos_e_vigencia(catalog, pdf):
    quote = extract_quote(*pdf)
    product = quote.products[0]
    first = make_catalog([
        ['00000333', 'INTRODUTOR RADIAL 6FR', 'MODELO A', product.anvisa, 'RAD6', '01/01/2026', '31/12/2026'],
        ['00000222', 'INTRODUTOR RADIAL 6FR', 'MODELO A', product.anvisa, 'RAD7'],
    ])
    second = make_catalog([['00000777', 'OUTRO PRODUTO', 'MODELO X', '10000000001']])
    v2 = import_bases(catalog, (first, FILENAMES[0]), (second, FILENAMES[1]), 'v2')
    assert v2.shared_anvisa == 1
    assert lookup_products(catalog, (product,), date(2026, 11, 18))[1][0].code == '00000333'
    for date_issued in (date(2027, 1, 1), None):
        result = lookup_products(catalog, (product,), date_issued)[1][0]
        assert not result.code and len(result.candidates) == 2
    restore_version(catalog, 1)
    assert lookup_products(catalog, (product,), quote.issued)[1][0].code == '00000123'


def test_atualizacao_invalida_preserva_versao(catalog):
    first = make_catalog([['00000333', 'TERMO', 'FABRICANTE', '10000000001']])
    invalid = make_catalog([['inválido', 'TERMO INVÁLIDO']])
    with pytest.raises(QuoteError, match='código ou termo inválido'):
        import_bases(catalog, (first, FILENAMES[0]), (invalid, FILENAMES[1]), 'inválida')
    active, versions = list_versions(catalog)
    assert active == 1 and len(versions) == 1


def test_nao_localizado_e_banco_indisponivel(catalog, pdf, tmp_path):
    quote = extract_quote(*pdf)
    unknown = replace(quote.products[0], reference='', anvisa='10000000099', description='VÁLVULA ABC')
    _, (result,) = lookup_products(catalog, (unknown,), quote.issued)
    assert not result.code and not result.candidates
    with pytest.raises(QuoteError, match='Banco TUSS indisponível'):
        lookup_products(tmp_path / 'ausente.sqlite3', (unknown,), quote.issued)
    broken = tmp_path / 'inválido.sqlite3'
    broken.write_bytes(b'nao sqlite')
    with pytest.raises(QuoteError, match='Banco TUSS indisponível'):
        lookup_products(broken, (unknown,), quote.issued)

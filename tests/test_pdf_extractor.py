from datetime import date
from decimal import Decimal

import pytest

from conftest import make_pdf
from src.models import QuoteError
from src.pdf_extractor import extract_quote


def test_layout_moeda_e_continuacao(pdf):
    quote = extract_quote(*pdf)
    first, second = quote.products
    assert quote.issued == date(2026, 11, 18)
    assert (first.reference, first.anvisa, first.brand) == ('RAD6', '01234567890', 'MODELO A')
    assert second.description == 'CONECT Y ACTP ROSQUEAV'
    assert (second.quantity, second.unit, second.total) == (3, 480, Decimal('1440.00'))


@pytest.mark.parametrize('kind', ['corrupt_total', 'partial'])
def test_rejeita_tabela_inconsistente(kind):
    with pytest.raises(QuoteError, match='diverge|incompletos'):
        extract_quote(*make_pdf(**{kind: True}))


@pytest.mark.parametrize('data', [b'fake', b'%PDF-corrompido'])
def test_pdf_invalido(data):
    with pytest.raises(QuoteError):
        extract_quote(data, 'orca.pdf')

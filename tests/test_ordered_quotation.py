from dataclasses import replace
from decimal import Decimal

from src.models import HospitalRow, Product
from src.workflow import _match_quotation
from src.material_matcher import match_products


def test_complete_ordered_quotation():
    rows = tuple(HospitalRow(i + 9, f'Pedido {i}', Decimal(2 if i in (15, 21) else 1)) for i in range(24))
    products = tuple(Product(f'Material {i}', 'MARCA', '12345678901', row.quantity,
                             Decimal(10), row.quantity * 10, str(i)) for i, row in enumerate(rows))
    matches = _match_quotation(products, rows)
    assert tuple(match.row for match in matches) == rows
    for altered in (products[:-1], (replace(products[0], quantity=Decimal(3)),) + products[1:]):
        assert _match_quotation(altered, rows) == match_products(altered, rows)
    unknown = (replace(rows[0], quantity=None),) + rows[1:]
    assert _match_quotation(products, unknown) == match_products(products, unknown)

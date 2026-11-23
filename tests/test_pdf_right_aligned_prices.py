from decimal import Decimal

from src.pdf_extractor import _columns, _product


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

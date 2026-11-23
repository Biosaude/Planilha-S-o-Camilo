import re
from dataclasses import dataclass
from decimal import Decimal

from .models import HospitalRow, Match, Product
from .validators import anvisa_key, normalized, reference_key

DOMAIN_TERMS = {
    'femu': 'femoral', 'femor': 'femoral', 'conect': 'conector',
    'rosqueav': 'rosqueavel', 'hidrofil': 'hidrofilico',
}
TYPE_PATTERNS = (
    ('guidewire', r'\b(?:fio guia|microguia|micro guia|guidewire)\b'),
    ('introducer', r'\bintrodutor\b'),
    ('stopcock', r'\btorneirinha\b'),
    ('y_connector', r'\bconector y\b'),
    ('microcatheter', r'\b(?:microcateter|micro cateter)\b'),
    ('catheter', r'\bcateter\b'),
    ('drain', r'\bdreno\b'),
)
FEATURES = {'radial', 'femoral', 'soft', 'stiff', 'rosqueavel', 'duplo', 'hidrofilico',
            'hidrofilica', 'complacente', 'destacavel', 'nao destacavel', 'backup', 'troca'}


@dataclass(frozen=True)
class Material:
    label: str
    kind: str
    gauge: frozenset[Decimal]
    length: Decimal | None
    diameter: Decimal | None
    ports: str
    features: frozenset[str]


def _decimal(value):
    return Decimal(value.replace(',', '.'))


def material(value: str) -> Material:
    label = ' '.join(DOMAIN_TERMS.get(word, word) for word in normalized(value).split())
    kind = next((kind for kind, pattern in TYPE_PATTERNS if re.search(pattern, label)), '')
    gauge = re.search(r'\b(\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)*)\s*f(?:r|rench)?\b', value, re.I)
    length = re.search(r'\b(\d+(?:[.,]\d+)?)\s*(cm|mm)\b', value, re.I)
    diameter = re.search(r'\b(0[.,]\d+)\s*(?:in\b|pol\b|"|x\s*\d)', value, re.I)
    pair = re.search(r'\b(0[.,]\d+)\s*x\s*(\d+(?:[.,]\d+)?)', value, re.I) if kind == 'guidewire' else None
    ports = re.search(r'\btorneirinha\s+(\d+)\b|\b(\d+)\s+vias\b', label)
    features = {term for term in FEATURES if re.search(rf'\b{term}\b', label)}
    if 'nao destacavel' in features:
        features.discard('destacavel')
    if 'hidrofilica' in features:
        features.remove('hidrofilica')
        features.add('hidrofilico')
    return Material(
        label, kind,
        frozenset(_decimal(part.strip()) for part in gauge[1].split('/')) if gauge else frozenset(),
        _decimal(length[1]) / (10 if length[2].lower() == 'mm' else 1) if length else
        _decimal(pair[2]) if pair else None,
        _decimal(diameter[1]) if diameter else None,
        (ports[1] or ports[2]) if ports else '',
        frozenset(features),
    )


def same_brand(requested: str, offered: str) -> bool:
    a, b = normalized(requested), normalized(offered)
    if not a or not b:
        return False
    shorter, longer = sorted((a, b), key=len)
    return longer == shorter or (len(shorter) >= 4 and longer.startswith(shorter + ' '))


def technical_conflicts(requested: Material, offered: Material) -> tuple[str, ...]:
    conflicts = []
    if requested.kind and offered.kind and requested.kind != offered.kind:
        conflicts.append('tipo de dispositivo')
    if requested.gauge and offered.gauge and requested.gauge.isdisjoint(offered.gauge):
        conflicts.append('calibre')
    for name, expected, actual in (
        ('comprimento', requested.length, offered.length),
        ('diâmetro', requested.diameter, offered.diameter),
        ('número de vias', requested.ports, offered.ports),
    ):
        if expected and actual and expected != actual:
            conflicts.append(name)
    for pair in ({'radial', 'femoral'}, {'soft', 'stiff'}, {'destacavel', 'nao destacavel'}):
        if requested.features & pair and offered.features & pair and not requested.features & offered.features & pair:
            conflicts.extend(sorted((requested.features | offered.features) & pair))
    if 'duplo' in offered.features and 'duplo' not in requested.features and requested.kind == 'y_connector':
        conflicts.append('conector duplo')
    return tuple(conflicts)


def _technical_match(requested, offered):
    if requested.label == offered.label:
        return True
    if not requested.kind or requested.kind != offered.kind:
        return False
    if requested.features - offered.features:
        return False
    if (requested.gauge and not offered.gauge) or (requested.length and not offered.length):
        return False
    if requested.diameter and not offered.diameter:
        return False
    if requested.ports and not offered.ports:
        return False

    if requested.kind == 'introducer':
        return bool(requested.gauge & offered.gauge and requested.features & {'radial', 'femoral'})
    if requested.kind == 'stopcock':
        return bool(requested.ports and requested.ports == offered.ports)
    if requested.kind == 'y_connector':
        return 'rosqueavel' in requested.features or 'duplo' in requested.features
    if requested.kind == 'guidewire':
        return bool(requested.diameter and requested.length)
    return False


def review_warnings(product: Product, row: HospitalRow) -> tuple[str, ...]:
    requested, offered = material(row.description), material(product.description)
    warnings = list(technical_conflicts(requested, offered))
    if requested.kind != offered.kind and requested.label != offered.label and not warnings:
        warnings.append('tipo de dispositivo sem confirmação')
    if row.reference and reference_key(row.reference) != reference_key(product.reference):
        warnings.append('referência')
    if row.anvisa and anvisa_key(row.anvisa) != anvisa_key(product.anvisa):
        warnings.append('ANVISA')
    if row.brand and not same_brand(row.brand, product.brand):
        warnings.append('marca')
    missing = requested.features - offered.features
    if missing:
        warnings.append('especificações sem confirmação no PDF: ' + ', '.join(sorted(missing)))
    if row.quantity is None:
        warnings.append('quantidade solicitada indisponível')
    return tuple(warnings)


def match_products(products: tuple[Product, ...], rows: tuple[HospitalRow, ...]) -> tuple[Match, ...]:
    requests = [(row, material(row.description)) for row in rows]
    matches = []
    for product in products:
        offered = material(product.description)
        options, exact, technical = [], [], []
        for row, requested in requests:
            if row.quantity is not None and row.quantity != product.quantity:
                continue
            exact_ref = bool(row.reference and reference_key(row.reference) == reference_key(product.reference))
            if not (exact_ref or (requested.kind and requested.kind == offered.kind)
                    or requested.label == offered.label):
                continue
            options.append(row)
            contradicted = technical_conflicts(requested, offered)
            brand_differs = row.brand and not same_brand(row.brand, product.brand)
            registration_differs = row.anvisa and anvisa_key(row.anvisa) != anvisa_key(product.anvisa)
            if contradicted or brand_differs or registration_differs or row.quantity is None:
                continue
            if exact_ref:
                exact.append(row)
            elif not row.reference and _technical_match(requested, offered):
                technical.append(row)
        confident = exact or technical
        matches.append(Match(confident[0] if len(confident) == 1 else None, tuple(options)))
    claimed = [match.row.number for match in matches if match.row]
    return tuple(
        Match(None, match.candidates) if match.row and claimed.count(match.row.number) > 1 else match
        for match in matches
    )

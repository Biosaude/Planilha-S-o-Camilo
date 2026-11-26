from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class QuoteError(ValueError):
    """Erro de processamento que pode ser exibido ao operador."""


@dataclass(frozen=True)
class Product:
    description: str
    brand: str
    anvisa: str
    quantity: Decimal
    unit: Decimal
    total: Decimal
    reference: str = ''


@dataclass(frozen=True)
class Quote:
    products: tuple[Product, ...]
    issued: date | None = None


@dataclass(frozen=True)
class HospitalRow:
    number: int
    description: str
    quantity: Decimal | None
    reference: str = ''
    brand: str = ''
    anvisa: str = ''


@dataclass(frozen=True)
class HospitalSheet:
    title: str
    quantity_column: int | None
    rows: tuple[HospitalRow, ...]
    has_unreadable_quantities: bool = False


@dataclass(frozen=True)
class Match:
    row: HospitalRow | None
    candidates: tuple[HospitalRow, ...] = ()


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    description: str
    model: str
    manufacturer: str
    anvisa: str
    starts: str
    ends: str
    risk: str
    technical_name: str
    source: int
    sheet: str
    row: int


@dataclass(frozen=True)
class TussResult:
    code: str = ''
    candidates: tuple[CatalogEntry, ...] = ()

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .excel_reader import read_hospital
from .excel_writer import export_workbook
from .material_matcher import match_products
from .models import HospitalSheet, Match, Quote, QuoteError, TussResult
from .pdf_extractor import extract_quote
from .security import record_audit
from .tuss_repository import lookup_products


@dataclass(frozen=True)
class Analysis:
    key: str
    quote: Quote
    hospital: HospitalSheet
    matches: tuple[Match, ...]
    catalog_version: int
    tuss: tuple[TussResult, ...]


def _match_quotation(products, rows):
    # Complete quotations are prepared in the hospital's requested order.
    if products and len(products) == len(rows) and all(
        row.quantity is not None and row.quantity == product.quantity
        for product, row in zip(products, rows, strict=True)
    ):
        return tuple(Match(row) for row in rows)
    return match_products(products, rows)


def analyze(excel: tuple[bytes, str], pdf: tuple[bytes, str], database: Path) -> Analysis:
    hospital = read_hospital(*excel)
    quote = extract_quote(*pdf)
    matches = _match_quotation(quote.products, hospital.rows)
    version, tuss = lookup_products(database, quote.products, quote.issued)
    return Analysis(uuid4().hex, quote, hospital, matches, version, tuss)


def generate(
    excel: tuple[bytes, str], analysis: Analysis, decisions: dict[int, int | None],
    audit: Path, actor: str, role: str,
) -> bytes:
    assignments = []
    audit_rows = []
    rows = {row.number: row for row in analysis.hospital.rows}
    for index, (product, match, tuss) in enumerate(
        zip(analysis.quote.products, analysis.matches, analysis.tuss, strict=True)
    ):
        if match.row:
            row = match.row.number
        elif index not in decisions:
            raise QuoteError('Conclua a revisão dos itens pendentes antes de exportar.')
        else:
            row = decisions[index]
            if row is not None and (row not in rows or (
                rows[row].quantity is not None and rows[row].quantity != product.quantity
            )):
                raise QuoteError('A linha confirmada é inválida ou tem quantidade divergente.')
            audit_rows.append((index + 1, row, 'confirmado_manual' if row else 'omitido_manual'))
        if row is not None:
            assignments.append((row, product, tuss.code))
    result = export_workbook(*excel, analysis.hospital, assignments)
    if audit_rows:
        record_audit(audit, analysis.key, analysis.catalog_version, actor, role, audit_rows)
    return result

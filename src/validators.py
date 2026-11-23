import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from unicodedata import normalize as unicode_normalize
from zipfile import ZipFile

from openpyxl import load_workbook

from .models import QuoteError

MAX_UPLOAD = 25 * 1024 * 1024
MAX_EXPANDED_XLSX = 200 * 1024 * 1024
CENT = Decimal('0.01')
MONEY_PATTERN = r'(?:R\$\s*)?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}'


def normalized(value: object) -> str:
    decomposed = unicode_normalize('NFKD', str(value or '').casefold())
    ascii_text = ''.join(char for char in decomposed if not '\u0300' <= char <= '\u036f')
    return ' '.join(re.findall(r'[a-z0-9]+', ascii_text))


def text_value(value: object) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def reference_key(value: str) -> str:
    return normalized(value).replace(' ', '')


def anvisa_key(value: str) -> str:
    if not re.fullmatch(r'[0-9.\-\s]+', value or ''):
        return ''
    digits = re.sub(r'\D', '', value)
    return digits if len(digits) == 11 else ''


def date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = text_value(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        return datetime.strptime(text, '%d/%m/%Y').date()


def quantity(value: object) -> Decimal | None:
    try:
        if isinstance(value, str):
            if not re.fullmatch(r'\d+(?:,\d{1,6})?', value.strip()):
                return None
            value = value.strip().replace(',', '.')
        number = Decimal(str(value))
        return number if number.is_finite() and 0 < number <= 1_000_000 else None
    except (InvalidOperation, ValueError):
        return None


def money(value: str) -> Decimal:
    clean = value.strip()
    if not re.fullmatch(MONEY_PATTERN, clean):
        raise QuoteError('Valor monetário fora do formato brasileiro.')
    amount = Decimal(clean.replace('R$', '').strip().replace('.', '').replace(',', '.'))
    if amount.as_tuple().digits and len(amount.as_tuple().digits) > 15:
        raise QuoteError('Valor monetário excede a precisão do Excel.')
    return amount


def financial_total(units: Decimal, unit: Decimal) -> Decimal:
    return (units * unit).quantize(CENT, rounding=ROUND_HALF_UP)


def validate_upload(payload: bytes, name: str, suffix: str) -> None:
    if not name.lower().endswith(suffix) or not payload or len(payload) > MAX_UPLOAD:
        raise QuoteError(f'Envie um arquivo {suffix} de até 25 MB.')


def open_xlsx(payload: bytes, name: str, *, read_only: bool = False, data_only: bool = False):
    validate_upload(payload, name, '.xlsx')
    try:
        with ZipFile(BytesIO(payload)) as archive:
            entries = archive.infolist()
            total_size = sum(entry.file_size for entry in entries)
            if (
                len(entries) > 10_000
                or total_size > MAX_EXPANDED_XLSX
                or len({entry.filename for entry in entries}) != len(entries)
                or any(entry.flag_bits & 1 for entry in entries)
            ):
                raise QuoteError('O Excel excede os limites de leitura segura ou está criptografado.')
            if '[Content_Types].xml' not in archive.namelist():
                raise QuoteError('O arquivo enviado não tem a estrutura de um Excel .xlsx.')
        return load_workbook(
            BytesIO(payload), read_only=read_only, data_only=data_only, keep_links=True,
            rich_text=not read_only,
        )
    except QuoteError:
        raise
    except Exception as exc:
        raise QuoteError('Não foi possível ler o Excel. Confira se o arquivo está íntegro.') from exc

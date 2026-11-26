import posixpath
import re
from copy import copy
from decimal import Decimal
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from lxml import etree
from openpyxl.cell.cell import MergedCell
from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter, range_boundaries

from .excel_reader import TARGETS, read_hospital
from .models import HospitalSheet, Product, QuoteError
from .validators import financial_total, open_xlsx

MAIN = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PKG_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
WORKBOOK_PART = 'xl/workbook.xml'
SUPPLIER_NAME = r'biosa[uú]\u0301?de'
SUPPLIER_SUFFIX = re.compile(rf'(?:(?:\s*[-–—]\s*|\s+){SUPPLIER_NAME})+$', re.IGNORECASE)
SUM_RANGE = re.compile(r'=SUM\(([GH])([1-9][0-9]{0,6}):\1([1-9][0-9]{0,6})\)')
CALC_SETTINGS = {'calcMode': 'auto', 'fullCalcOnLoad': '1', 'forceFullCalc': '1', 'calcCompleted': '0'}


def _parse(payload):
    tree = etree.parse(BytesIO(payload), etree.XMLParser(resolve_entities=False, no_network=True))
    if tree.docinfo.doctype:
        raise QuoteError('O Excel contém uma definição XML que impede edição segura.')
    return tree


def _sheet_part(archive, sheet_title):
    paths = {name.casefold() for name in archive.namelist()}
    if any(name.startswith(('_xmlsignatures/', 'xl/embeddings/', 'xl/activex/'))
           or name == 'xl/vbaproject.bin' for name in paths):
        raise QuoteError('O Excel contém assinatura digital ou conteúdo ativo incompatível com a edição segura.')
    workbook = _parse(archive.read(WORKBOOK_PART))
    relationships = _parse(archive.read('xl/_rels/workbook.xml.rels'))
    links = {link.get('Id'): link for link in relationships.iter(PKG_REL + 'Relationship')}
    for sheet in workbook.iter(MAIN + 'sheet'):
        if sheet.get('name') != sheet_title:
            continue
        link = links.get(sheet.get(REL + 'id'))
        if link is not None and link.get('Type', '').endswith('/worksheet') and link.get('TargetMode') != 'External':
            path = link.get('Target', '')
            path = posixpath.normpath(path.lstrip('/') if path.startswith('/') else f'xl/{path}')
            if path.startswith('xl/') and path in archive.namelist():
                return path
    raise QuoteError('Não foi possível localizar com segurança a aba original da cotação.')


def _formula_expression(cell):
    return re.sub(r'[\s$]', '', cell.value).upper() if isinstance(cell.value, str) else ''


def _row_total_mode(cell, quantity_column):
    if cell.column != 8 or quantity_column is None or cell.data_type != 'f':
        return None
    qty = get_column_letter(quantity_column) + str(cell.row)
    unit = 'G' + str(cell.row)
    expression = _formula_expression(cell)
    for multiplication in (f'{qty}*{unit}', f'{unit}*{qty}'):
        if expression == f'={multiplication}':
            return 'exact'
        if expression == f'=ROUND({multiplication},2)':
            return 'rounded'
    return None


def _matches_preserved_formula(cell, row, quantity_column, product):
    mode = _row_total_mode(cell, quantity_column)
    if mode is None or row.quantity != product.quantity:
        return False
    total = (financial_total(row.quantity, product.unit) if mode == 'rounded'
             else row.quantity * product.unit)
    return total == product.total


def _export_brand(value):
    brand = SUPPLIER_SUFFIX.sub('', value.strip()).rstrip()
    if not brand:
        return ''
    if re.fullmatch(SUPPLIER_NAME, brand, re.IGNORECASE):
        return 'BIOSAUDE'
    return f'{brand} - BIOSAUDE'


def _export_identifier(value):
    # O formato Geral pode abreviar identificadores mais longos em notação científica.
    if re.fullmatch(r'(?:0|[1-9][0-9]{0,10})', value):
        return int(value)
    return value


def _openpyxl_edits(workbook, hospital, assignments):
    sheet = workbook[hospital.title]
    if sheet.protection.sheet:
        raise QuoteError('A aba de cotação está protegida contra alterações.')
    rows = {row.number: row for row in hospital.rows}
    changes, cached = {}, {}
    for number, product, tuss in assignments:
        if number not in rows or (rows[number].quantity is not None and rows[number].quantity != product.quantity):
            raise QuoteError('A linha selecionada não pertence à cotação ou a quantidade diverge.')
        values = {
            2: _export_identifier(tuss) if tuss else None,
            4: product.description,
            5: _export_brand(product.brand) or None,
            6: ' - '.join(value for value in (product.anvisa, product.reference) if value) or None,
            7: product.unit,
            8: product.total,
        }
        for column, value in values.items():
            cell = sheet.cell(number, column)
            if isinstance(cell, MergedCell) or any(cell.coordinate in group for group in sheet.merged_cells.ranges):
                raise QuoteError(f'A célula {cell.coordinate} está mesclada e não pode ser preenchida.')
            if _matches_preserved_formula(cell, rows[number], hospital.quantity_column, product):
                cached[cell.coordinate] = product.total
                continue
            if cell.data_type in {'f', 'e'} or isinstance(cell.value, list) or cell.hyperlink:
                raise QuoteError(f'A célula {cell.coordinate} contém uma fórmula ou recurso incompatível com a edição.')
            if cell.value == value and cell.data_type != 'b':
                continue
            cell.value = value
            if isinstance(value, str):
                cell.data_type = 's'
                if cell.value != value:
                    raise QuoteError(f'O texto excede o limite da célula {cell.coordinate}.')
            changes[cell.coordinate] = cell
    cached.update(_sum_caches(sheet, hospital.quantity_column, cached))
    return changes, cached


def _numeric_value(cell, *, ignore_text=False):
    if cell.value is None or (ignore_text and cell.data_type in {'s', 'inlineStr', 'b'}):
        return Decimal(0)
    if cell.data_type == 'b':
        return Decimal(int(cell.value))
    if cell.data_type == 'n' and isinstance(cell.value, (int, float, Decimal)):
        number = Decimal(str(cell.value))
        return number if number.is_finite() else None
    return None


def _sum_operand(cell, sheet, quantity_column, known):
    if cell.coordinate in known:
        return known[cell.coordinate]
    mode = _row_total_mode(cell, quantity_column)
    if mode is None:
        return _numeric_value(cell, ignore_text=True)
    units = _numeric_value(sheet.cell(cell.row, quantity_column))
    price = _numeric_value(sheet.cell(cell.row, 7))
    if units is None or price is None:
        return None
    return financial_total(units, price) if mode == 'rounded' else units * price


def _sum_caches(sheet, quantity_column, known):
    totals = {}
    for row in sheet.iter_rows(min_col=7, max_col=8):
        for cell in row:
            if cell.data_type != 'f':
                continue
            match = SUM_RANGE.fullmatch(_formula_expression(cell))
            if not match or match[1] != cell.column_letter:
                continue
            first, last = sorted((int(match[2]), int(match[3])))
            if last > 1_048_576 or first <= cell.row <= last:
                continue
            total = Decimal(0)
            for number in range(first, min(sheet.max_row, last) + 1):
                value = _sum_operand(sheet.cell(number, cell.column), sheet, quantity_column, known)
                if value is None:
                    break
                total += value
            else:
                if len(total.normalize().as_tuple().digits) <= 15:
                    totals[cell.coordinate] = total
    return totals


def _cells(tree):
    for row in tree.iter(MAIN + 'row'):
        for element in row.iterchildren(MAIN + 'c'):
            yield element


def _write_cell(tree, changes):
    row_elements = {int(row.get('r')): row for row in tree.iter(MAIN + 'row')}
    existing_cells = {element.get('r'): element for element in _cells(tree)}
    formula_ranges = [
        range_boundaries(formula.get('ref')) for formula in tree.iter(MAIN + 'f')
        if formula.get('t') in {'array', 'dataTable', 'shared'} and formula.get('ref')
    ]
    previous = {}
    for coordinate, cell in changes.items():
        if any(left <= cell.column <= right and top <= cell.row <= bottom
               for left, top, right, bottom in formula_ranges):
            raise QuoteError(f'A célula {coordinate} faz parte de um intervalo calculado.')
        element = existing_cells.get(coordinate)
        if element is None:
            row = row_elements.get(cell.row)
            if row is None:
                raise QuoteError(f'A linha {cell.row} não existe no XML original.')
            element = etree.Element(MAIN + 'c', r=coordinate)
            for sibling in row:
                if sibling.tag != MAIN + 'c' or coordinate_to_tuple(sibling.get('r'))[1] > cell.column:
                    sibling.addprevious(element)
                    break
            else:
                row.append(element)
            previous[coordinate] = None
        else:
            if (any(key not in {'r', 's', 't'} for key in element.attrib)
                    or any(child.tag not in {MAIN + 'v', MAIN + 'is'} for child in element)):
                raise QuoteError(f'A célula {coordinate} contém metadados incompatíveis com edição segura.')
            previous[coordinate] = etree.tostring(element, with_tail=False)
            for child in tuple(element):
                element.remove(child)
        if cell.value is None:
            element.attrib.pop('t', None)
        elif cell.data_type == 's':
            element.set('t', 'inlineStr')
            inline = etree.SubElement(element, MAIN + 'is')
            text = etree.SubElement(inline, MAIN + 't')
            text.set(XML_SPACE, 'preserve')
            text.text = cell.value
        else:
            element.set('t', 'n')
            etree.SubElement(element, MAIN + 'v').text = str(cell.value)
    return previous


def _write_caches(tree, cached):
    written = set()
    for cell in _cells(tree):
        coordinate = cell.get('r')
        if coordinate not in cached:
            continue
        formula = cell.find(MAIN + 'f')
        values = cell.findall(MAIN + 'v')
        if formula is None or formula.get('t') not in {None, 'normal', 'shared'} or len(values) > 1:
            raise QuoteError(f'Não foi possível atualizar com segurança o resultado de {coordinate}.')
        value = values[0] if values else etree.Element(MAIN + 'v')
        if not values:
            formula.addnext(value)
        value.text = format(cached[coordinate], 'f')
        cell.set('t', 'n')
        written.add(coordinate)
    if written != cached.keys():
        raise QuoteError('Não foi possível localizar todas as fórmulas calculadas na aba de cotação.')


def _canonical(tree):
    return etree.tostring(tree, method='c14n', with_comments=True)


def _verify_sheet(original, modified, previous, cached):
    original_tree, modified_tree = _parse(original), _parse(modified)
    original_formulas = {cell.get('r'): cell for cell in _cells(original_tree) if cell.get('r') in cached}
    found = set()
    for cell in _cells(modified_tree):
        coordinate = cell.get('r')
        if coordinate in cached:
            original_cell = original_formulas[coordinate]
            if 't' in original_cell.attrib:
                cell.set('t', original_cell.get('t'))
            else:
                cell.attrib.pop('t', None)
            value = cell.find(MAIN + 'v')
            original_value = original_cell.find(MAIN + 'v')
            if original_value is None:
                cell.remove(value)
            else:
                cell.replace(value, copy(original_value))
        if coordinate not in previous:
            continue
        if coordinate in found:
            raise QuoteError('O Excel apresenta células duplicadas após o preenchimento.')
        found.add(coordinate)
        old = previous[coordinate]
        if old is None:
            cell.getparent().remove(cell)
        else:
            old_cell = etree.fromstring(old)
            if cell.get('s') != old_cell.get('s'):
                raise QuoteError('Um estilo foi alterado durante o preenchimento do Excel.')
            old_cell.tail = cell.tail
            cell.getparent().replace(cell, old_cell)
    if found != previous.keys() or _canonical(original_tree) != _canonical(modified_tree):
        raise QuoteError('A conferência estrutural detectou alterações fora das células autorizadas.')


def _recalculate_workbook(payload):
    tree = _parse(payload)
    root = tree.getroot()
    calc = root.find(MAIN + 'calcPr')
    original = copy(calc) if calc is not None else None
    if calc is None:
        calc = etree.Element(MAIN + 'calcPr')
        successors = {'oleSize', 'customWorkbookViews', 'pivotCaches', 'smartTagPr',
                      'smartTagTypes', 'webPublishing', 'fileRecoveryPr', 'webPublishObjects', 'extLst'}
        for child in root:
            if isinstance(child.tag, str) and etree.QName(child).localname in successors:
                child.addprevious(calc)
                break
        else:
            root.append(calc)
    for key, value in CALC_SETTINGS.items():
        calc.set(key, value)
    updated = etree.tostring(tree, encoding='UTF-8', xml_declaration=True)
    # Verifica o XML regravado, restaurando somente os atributos autorizados.
    verified = _parse(updated)
    verified_calc = verified.getroot().find(MAIN + 'calcPr')
    if original is None:
        verified.getroot().remove(verified_calc)
    else:
        for key in CALC_SETTINGS:
            if key in original.attrib:
                verified_calc.set(key, original.get(key))
            else:
                verified_calc.attrib.pop(key, None)
    if _canonical(_parse(payload)) != _canonical(verified):
        raise QuoteError('A conferência detectou mudanças fora das configurações de recálculo.')
    return updated


def export_workbook(
    payload: bytes, name: str, hospital: HospitalSheet, assignments: list[tuple[int, Product, str]]
) -> bytes:
    numbers = [number for number, _, _ in assignments]
    if not numbers or len(set(numbers)) != len(numbers):
        raise QuoteError('Resolva linhas duplicadas ou selecione pelo menos um item para exportar.')
    if read_hospital(payload, name) != hospital:
        raise QuoteError('A planilha enviada mudou desde a análise. Processe a cotação novamente.')
    workbook = open_xlsx(payload, name)
    try:
        changes, cached = _openpyxl_edits(workbook, hospital, assignments)
        if any(cell.column not in TARGETS or cell.row not in numbers for cell in changes.values()):
            raise QuoteError('Foi solicitada uma alteração fora das posições autorizadas.')
        output = BytesIO()
        with ZipFile(BytesIO(payload)) as source:
            part = _sheet_part(source, hospital.title)
            base = source.read(part)
            tree = _parse(base)
            previous = _write_cell(tree, changes)
            _write_caches(tree, cached)
            updated = etree.tostring(tree, encoding='UTF-8', xml_declaration=True) if changes or cached else base
            _verify_sheet(base, updated, previous, cached)
            replacements = {part: updated, WORKBOOK_PART: _recalculate_workbook(source.read(WORKBOOK_PART))}
            with ZipFile(output, 'w') as destination:
                destination.comment = source.comment
                for info in source.infolist():
                    content = source.read(info)
                    destination.writestr(copy(info), replacements.get(info.filename, content))
            result = output.getvalue()
            with ZipFile(BytesIO(result)) as destination:
                if (destination.namelist() != source.namelist()
                        or any(source.read(member) != destination.read(member)
                               for member in source.namelist() if member not in replacements)):
                    raise QuoteError('A exportação alterou partes não autorizadas do arquivo Excel.')
        verified = open_xlsx(result, name)
        try:
            for coordinate, expected in changes.items():
                copied = verified[hospital.title][coordinate]
                value = copied.value
                equal = Decimal(str(value)) == expected.value if isinstance(expected.value, Decimal) else value == expected.value
                if not equal or (expected.value is not None and copied.data_type != expected.data_type):
                    raise QuoteError(f'O valor da célula {coordinate} não foi preservado na exportação.')
        finally:
            verified.close()
        if cached:
            data = open_xlsx(result, name, data_only=True)
            try:
                for coordinate, expected in cached.items():
                    cell = data[hospital.title][coordinate]
                    if cell.data_type != 'n' or cell.value is None or _numeric_value(cell) != expected:
                        raise QuoteError(f'O resultado calculado de {coordinate} não foi preservado.')
            finally:
                data.close()
        return result
    except (KeyError, ValueError, TypeError, OverflowError, BadZipFile, etree.LxmlError) as exc:
        if isinstance(exc, QuoteError):
            raise
        raise QuoteError('Não foi possível preservar a estrutura do Excel durante a exportação.') from exc
    finally:
        workbook.close()

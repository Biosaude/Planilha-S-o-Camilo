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
    workbook = _parse(archive.read('xl/workbook.xml'))
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


def _matches_preserved_formula(cell, row, quantity_column, product):
    if cell.column != 8 or quantity_column is None or not isinstance(cell.value, str):
        return False
    qty = get_column_letter(quantity_column) + str(row.number)
    unit = 'G' + str(row.number)
    expression = re.sub(r'[\s$]', '', cell.value).upper()
    if row.quantity != product.quantity:
        return False
    products = {f'{qty}*{unit}', f'{unit}*{qty}'}
    if expression in {f'={terms}' for terms in products}:
        return row.quantity * product.unit == product.total
    if expression in {f'=ROUND({terms},2)' for terms in products}:
        return financial_total(row.quantity, product.unit) == product.total
    return False


def _openpyxl_edits(workbook, hospital, assignments):
    if workbook.calculation and workbook.calculation.calcMode == 'manual':
        raise QuoteError('O Excel está em modo de cálculo manual. Use o modelo com cálculo automático.')
    sheet = workbook[hospital.title]
    if sheet.protection.sheet:
        raise QuoteError('A aba de cotação está protegida contra alterações.')
    rows = {row.number: row for row in hospital.rows}
    changes = {}
    for number, product, tuss in assignments:
        if number not in rows or (rows[number].quantity is not None and rows[number].quantity != product.quantity):
            raise QuoteError('A linha selecionada não pertence à cotação ou a quantidade diverge.')
        values = {2: tuss or None, 4: product.description, 5: product.brand, 6: product.anvisa,
                  7: product.unit, 8: product.total}
        for column, value in values.items():
            cell = sheet.cell(number, column)
            if isinstance(cell, MergedCell) or any(cell.coordinate in group for group in sheet.merged_cells.ranges):
                raise QuoteError(f'A célula {cell.coordinate} está mesclada e não pode ser preenchida.')
            if cell.data_type == 'f' and _matches_preserved_formula(cell, rows[number], hospital.quantity_column, product):
                continue
            if cell.data_type in {'f', 'e'} or isinstance(cell.value, list) or cell.hyperlink:
                raise QuoteError(f'A célula {cell.coordinate} contém uma fórmula ou recurso incompatível com a edição.')
            if cell.value == value:
                continue
            cell.value = value
            if isinstance(value, str):
                cell.data_type = 's'
                if cell.value != value:
                    raise QuoteError(f'O texto excede o limite da célula {cell.coordinate}.')
            changes[cell.coordinate] = cell
    return changes


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


def _verify_sheet(original, modified, previous):
    original_tree, modified_tree = _parse(original), _parse(modified)
    found = {}
    for cell in _cells(modified_tree):
        coordinate = cell.get('r')
        if coordinate not in previous:
            continue
        if coordinate in found:
            raise QuoteError('O Excel apresenta células duplicadas após o preenchimento.')
        found[coordinate] = True
        old = previous[coordinate]
        if old is None:
            cell.getparent().remove(cell)
        else:
            old_cell = etree.fromstring(old)
            if cell.get('s') != old_cell.get('s'):
                raise QuoteError('Um estilo foi alterado durante o preenchimento do Excel.')
            old_cell.tail = cell.tail
            cell.getparent().replace(cell, old_cell)
    if found.keys() != previous.keys() or etree.tostring(
        original_tree, method='c14n', with_comments=True
    ) != etree.tostring(modified_tree, method='c14n', with_comments=True):
        raise QuoteError('A conferência estrutural detectou alterações fora das células autorizadas.')


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
        changes = _openpyxl_edits(workbook, hospital, assignments)
        if any(cell.column not in TARGETS or cell.row not in numbers for cell in changes.values()):
            raise QuoteError('Foi solicitada uma alteração fora das posições autorizadas.')
        output = BytesIO()
        with ZipFile(BytesIO(payload)) as source:
            part = _sheet_part(source, hospital.title)
            base = source.read(part)
            if not changes:
                return payload
            tree = _parse(base)
            previous = _write_cell(tree, changes)
            updated = etree.tostring(tree, encoding='UTF-8', xml_declaration=True)
            _verify_sheet(base, updated, previous)
            with ZipFile(output, 'w') as destination:
                destination.comment = source.comment
                for info in source.infolist():
                    content = source.read(info)
                    destination.writestr(copy(info), updated if info.filename == part else content)
            result = output.getvalue()
            with ZipFile(BytesIO(result)) as destination:
                if (destination.namelist() != source.namelist()
                        or any(source.read(member) != destination.read(member)
                               for member in source.namelist() if member != part)):
                    raise QuoteError('A exportação alterou partes não autorizadas do arquivo Excel.')
        verified = open_xlsx(result, name)
        try:
            for coordinate, expected in changes.items():
                value = verified[hospital.title][coordinate].value
                equal = Decimal(str(value)) == expected.value if isinstance(expected.value, Decimal) else value == expected.value
                if not equal:
                    raise QuoteError(f'O valor da célula {coordinate} não foi preservado na exportação.')
        finally:
            verified.close()
        return result
    except (KeyError, ValueError, TypeError, OverflowError, BadZipFile, etree.LxmlError) as exc:
        if isinstance(exc, QuoteError):
            raise
        raise QuoteError('Não foi possível preservar a estrutura do Excel durante a exportação.') from exc
    finally:
        workbook.close()

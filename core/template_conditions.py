"""Evaluate the row requirements embedded in Amazon's Excel templates."""
import ast
import re
from functools import lru_cache


@lru_cache(maxsize=2048)
def _expression(formula):
    # Translate only the Excel cell/literal notation. The interpreter below
    # accepts a closed set of nodes and never executes workbook code.
    def token(match):
        text = match[0]
        if text.startswith('"'):
            return repr(text[1:-1].replace('""', '"').casefold())
        if text.startswith('Template!'):
            return 'cell_' + re.search(r'\$([A-Z]+)', text)[1]
        return {'=': '==', '<>': '!=', 'TRUE': 'True', 'FALSE': 'False'}[text]
    text = re.sub(r'"(?:[^"]|"")*"|Template!\$[A-Z]+\$?1\b|<>|=|\bTRUE\b|\bFALSE\b', token, formula)
    return ast.parse(text, mode='eval').body


def _value(node, cells, lists):
    if isinstance(node, ast.Constant) and type(node.value) in (str, int, bool):
        return node.value
    if isinstance(node, ast.Name):
        if node.id.startswith('cell_'):
            return cells.get(node.id[5:], '')
        return lists[node.id]
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right = (_value(x, cells, lists) for x in (node.left, node.comparators[0]))
        if isinstance(node.ops[0], ast.Eq): return left == right
        if isinstance(node.ops[0], ast.NotEq): return left != right
        if isinstance(node.ops[0], ast.Gt): return left > right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        args = [_value(x, cells, lists) for x in node.args]
        op = node.func.id
        if op == 'AND': return all(args)
        if op == 'OR': return any(args)
        if op == 'IF' and len(args) == 3: return args[1] if args[0] else args[2]
        if op == 'NOT' and len(args) == 1: return not args[0]
        if op == 'LEN' and len(args) == 1: return len(str(args[0]))
        if op == 'COUNTIF' and len(args) == 2 and isinstance(args[0], tuple):
            if any(ch in str(args[1]) for ch in '*?~'): raise ValueError('Unsupported wildcard criterion')
            return args[0].count(args[1])
    raise ValueError('Unsupported Excel requirement expression')


def workbook_conditions(wb, sheet, fields, product_type, definitions, data_row):
    from openpyxl.utils.cell import get_column_letter, range_boundaries
    columns = {key:get_column_letter(col) for key,col in fields.items()}
    conditional = {columns[d['field']]:d['field'] for d in definitions
                   if d.get('required','').casefold() == 'conditionally required' and d['field'] in fields}
    lists = {}
    for name, definition in wb.defined_names.items():
        if not re.fullmatch(r'CONDITION_LIST_\d+', name): continue
        for tab, address in definition.destinations:
            if tab != 'Conditions List' or tab not in wb: continue
            c1,r1,c2,r2 = range_boundaries(address)
            if c1 != c2 or not r1 or not r2 or r2-r1 > 1024: continue
            lists[name] = tuple(str(wb[tab].cell(r,c1).value or '').casefold() for r in range(r1,r2+1))
    rules = {}
    for region in sheet.conditional_formatting:
        for area in region.sqref.ranges:
            field = conditional.get(get_column_letter(area.min_col))
            if not field or area.min_col != area.max_col or not area.min_row <= data_row <= area.max_row: continue
            program = []
            for rule in sorted(sheet.conditional_formatting[region], key=lambda x:x.priority):
                formula = (rule.formula or [''])[0]
                if re.fullmatch(r'ApplicablePTList\d+', formula):
                    defined = wb.defined_names.get(formula)
                    if defined is None or not _applicable_product(defined.attr_text, product_type):
                        program = []
                        break
                    continue
                if formula == f'IF(LEN({columns[field]}{area.min_row})>0,1,0)': continue
                gate = re.fullmatch(r'IF\((PTList\d+),((req_tog|req|for_min|for_maxf|only_enf|form_rg)PTList\d+[\w.]+),0\)',formula)
                if not gate or not rule.stopIfTrue or gate[1] not in wb.defined_names or gate[2] not in wb.defined_names:
                    program = []
                    break
                if wb.defined_names[gate[1]].attr_text != f'Template!$B1="{product_type}"':
                    program = []
                    break
                program.append((gate[3] in ('req','req_tog','for_min'), wb.defined_names[gate[2]].attr_text))
            if program and any(required for required,_ in program):
                rules[field] = program
    return columns, lists, rules, product_type.casefold()


def _applicable_product(formula, product_type):
    # These rules shade a cell when its template product type is *not* applicable.
    try:
        tree = _expression(formula)
        cells = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.startswith('cell_')}
        return cells == {'cell_B'} and _value(tree, {'B':product_type.casefold()}, {}) is False
    except (ValueError, TypeError, KeyError, SyntaxError, RecursionError):
        return False


def row_applicability(conditions, values):
    if not conditions: return {}
    columns, lists, rules, product_type = conditions
    cells = {columns[k]:str(v).casefold() for k,v in values.items() if k in columns}
    if not product_type or cells.get('B') != product_type:
        return {}
    decisions = {}
    for field, program in rules.items():
        if field in values: continue
        try:
            decisions[field] = next((required for required,formula in program
                                     if _value(_expression(formula),cells,lists)), False)
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError):
            continue  # Unrecognized template formulas remain with the existing three-state resolver.
    return decisions

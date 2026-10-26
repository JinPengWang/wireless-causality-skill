"""Recompute atomic numerical claims from hashed scalar/vector locations and unit-aware expressions."""
import argparse
import ast
import math
import re
from dataclasses import dataclass
from pathlib import Path
from common import finite_number as basic_number, read_json, sha256, table_rows, write_json, ensure_output_safe
from investigation_io import artifact, provenance


def finite_number(value, label, positive=False):
    # Float64 calculations are deliberately not advertised as exact large-integer arithmetic.
    if type(value) is int or (isinstance(value, str) and re.fullmatch(r'[+-]?[0-9]+', value.strip())):
        if abs(int(value)) > 2**53:
            raise ValueError(label + ': integer exceeds exact float64 range; use a reviewed exact-arithmetic adapter')
    return basic_number(value, label, positive)


@dataclass
class Quantity:
    value: object
    dimensions: dict


DEFAULT_UNITS = {
    '1': ({}, 1.), '%': ({}, .01),
    's': ({'time': 1}, 1.), 'ms': ({'time': 1}, .001), 'us': ({'time': 1}, .000001),
    'bit': ({'information': 1}, 1.), 'byte': ({'information': 1}, 8.),
    'bit/s': ({'information': 1, 'time': -1}, 1.), 'kbit/s': ({'information': 1, 'time': -1}, 1000.),
    'Mbit/s': ({'information': 1, 'time': -1}, 1000000.), 'Mbps': ({'information': 1, 'time': -1}, 1000000.),
    'byte/s': ({'information': 1, 'time': -1}, 8.),
    'count': ({'count': 1}, 1.), 'count/s': ({'count': 1, 'time': -1}, 1.),
    'Hz': ({'time': -1}, 1.), 'dB': ({'log_ratio': 1}, 1.)
}


def unit_registry(custom):
    units = dict(DEFAULT_UNITS)
    for name, spec in custom.items():
        if name in units or not isinstance(name, str) or not name.strip():
            raise ValueError('Do not redefine built-in units; use a distinct custom unit name')
        dims = spec['dimensions']
        if not isinstance(dims, dict) or any(not isinstance(k, str) or type(v) is not int for k, v in dims.items()):
            raise ValueError('Custom dimensions require named integer powers')
        units[name] = ({k:v for k,v in dims.items() if v}, finite_number(spec['scale'], 'unit scale', positive=True))
    return units


def resolve_pointer(value, pointer):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith('/')):
        raise ValueError('Invalid JSON pointer')
    for raw in pointer.split('/')[1:] if pointer else []:
        if re.search(r'~(?![01])', raw):
            raise ValueError('Invalid JSON pointer escape')
        key = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', key) and int(key) < len(value):
            value = value[int(key)]
        else:
            raise ValueError('JSON pointer does not resolve: ' + pointer)
    return value


def select(path, locator, cache):
    if not isinstance(locator, dict):
        raise ValueError('Use an explicit value locator')
    if locator.get('type') == 'json_pointer':
        if path.suffix.lower() != '.json':
            raise ValueError('JSON pointer requires a JSON artifact')
        if path not in cache:
            cache[path] = read_json(path)
        return resolve_pointer(cache[path], locator['pointer'])
    if locator.get('type') in {'table_rows', 'table_cell'}:
        rows = [locator.get('row')] if locator['type'] == 'table_cell' else locator.get('rows')
        field = locator.get('field')
        if not isinstance(rows, list) or not rows or any(type(r) is not int or r < 1 for r in rows) or len(set(rows)) != len(rows):
            raise ValueError('Specify distinct positive table row numbers')
        if not isinstance(field, str) or not field:
            raise ValueError('Specify the exact table field')
        header = locator.get('header_row', 1)
        if any(row <= header for row in rows):
            raise ValueError('Value rows must follow the header')
        key = (path, locator.get('sheet'), header, tuple(rows), field)
        if key not in cache:
            found = {}
            for row, values in table_rows(path, locator.get('sheet'), header, required_columns=[field]):
                if row in rows:
                    found[row] = values[field]
                if row >= max(rows):
                    break
            if set(found) != set(rows):
                raise ValueError('One or more selected table rows are absent')
            cache[key] = [found[row] for row in rows]
        values = cache[key]
        return values[0] if locator['type'] == 'table_cell' else values
    raise ValueError('Numerical checks support json_pointer or table_rows; figures/text need a separately recorded manual check')


def expression_value(expression, operands):
    tree = ast.parse(expression, mode='eval')
    if len(list(ast.walk(tree))) > 128:
        raise ValueError('Expression is too complex; split the numerical claim')
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in operands}
    if referenced != set(operands):
        raise ValueError('Every declared evidence operand must be used by the expression')
    def scalar(q):
        if isinstance(q.value, list):
            raise ValueError('Reduce vectors explicitly with sum/mean/min/max/count')
        return finite_number(q.value, 'expression value')
    def visit(node):
        if isinstance(node, ast.Name) and node.id in operands:
            return operands[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            return Quantity(finite_number(node.value, 'constant'), {})
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            q = visit(node.operand)
            return Quantity((-1 if isinstance(node.op, ast.USub) else 1)*scalar(q), q.dimensions)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            a, b = scalar(left), scalar(right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if left.dimensions != right.dimensions:
                    raise ValueError('Cannot add or subtract incompatible units')
                return Quantity(a+b if isinstance(node.op, ast.Add) else a-b, left.dimensions)
            sign = -1 if isinstance(node.op, ast.Div) else 1
            dims = dict(left.dimensions)
            for k, v in right.dimensions.items():
                dims[k] = dims.get(k, 0) + sign*v
            value = a/b if sign == -1 else a*b
            return Quantity(finite_number(value, 'calculated value'), {k:v for k,v in dims.items() if v})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1 and not node.keywords:
            name = node.func.id
            q = visit(node.args[0])
            if name == 'abs':
                return Quantity(abs(scalar(q)), q.dimensions)
            if name not in {'sum', 'mean', 'min', 'max', 'count'} or not isinstance(q.value, list) or not q.value:
                raise ValueError('Unsupported function or non-vector aggregate')
            if name == 'count':
                return Quantity(float(len(q.value)), {'count': 1})
            fn = {'sum': math.fsum, 'mean': lambda v:math.fsum(v)/len(v), 'min': min, 'max': max}[name]
            return Quantity(finite_number(fn(q.value), 'aggregate'), q.dimensions)
        raise ValueError('Unsupported expression; attributes, indexing and arbitrary code are forbidden')
    result = visit(tree.body)
    scalar(result)
    return result


def verify(bundle, base):
    if type(bundle.get('schema_version')) is not int or bundle.get('schema_version') != 1 or not isinstance(bundle.get('claims'), list) or not isinstance(bundle.get('artifacts'), dict):
        raise ValueError('Provide schema_version=1, artifacts mapping and atomic claims list')
    units = unit_registry(bundle.get('units', {}))
    cache, paths, artifact_results = {}, {}, {}
    for identity, spec in bundle['artifacts'].items():
        try:
            paths[identity] = artifact(base, spec)
            artifact_results[identity] = {'integrity': 'passed', 'path': str(paths[identity])}
        except (ValueError, OSError) as exc:
            artifact_results[identity] = {'integrity': 'failed', 'reason': str(exc)}
    results, ids = [], set()
    for claim in bundle['claims']:
        identity = claim.get('id')
        if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identity) or identity in ids:
            raise ValueError('Distinct safe claim ids are required')
        ids.add(identity)
        result = {'id': identity, 'meaning_verified': False, 'causal_truth_verified': False, 'operands': {}}
        try:
            if not isinstance(claim.get('statement'), str) or not claim['statement'].strip() or claim['statement'].strip().startswith(('REPLACE_', 'TODO', 'TBD')):
                raise ValueError('Provide the atomic numerical statement')
            if claim.get('verification', 'automatic') not in {'automatic', 'manual'}:
                raise ValueError('verification must be automatic or manual')
            if claim.get('verification') == 'manual':
                if not claim.get('reason'):
                    raise ValueError('Explain why this numerical claim needs manual verification')
                result.update(status='not_checked', reason=claim['reason'])
                results.append(result)
                continue
            operands = {}
            if not isinstance(claim.get('operands'), dict) or not claim['operands']:
                raise ValueError('Numerical claims need evidence operands, not only constants')
            for name, binding in claim['operands'].items():
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) or name in {'sum', 'mean', 'min', 'max', 'count', 'abs'}:
                    raise ValueError('Use distinct simple operand names, not function names')
                path = paths.get(binding['artifact'])
                if path is None:
                    raise ValueError('Operand artifact integrity failed or artifact id is unknown')
                value = select(path, binding['locator'], cache)
                unit = binding['unit']
                if unit not in units:
                    raise ValueError('Undeclared operand unit: ' + unit)
                if not isinstance(binding.get('unit_basis'), str) or not binding['unit_basis'].strip() or binding['unit_basis'].strip().startswith(('REPLACE_', 'TODO', 'TBD')):
                    raise ValueError('Declare the source measurement contract for each operand unit')
                dims, scale = units[unit]
                unit_check = 'declared_contract_only'
                if binding.get('unit_locator'):
                    actual = select(path, binding['unit_locator'], cache)
                    if not isinstance(actual, str) or actual not in units or units[actual] != units[unit]:
                        raise ValueError('Artifact unit disagrees with declared operand unit')
                    unit_check = 'matches_artifact_field'
                values = [finite_number(v, 'source value') for v in value] if isinstance(value, list) else finite_number(value, 'source value')
                operands[name] = Quantity([v*scale for v in values] if isinstance(values, list) else values*scale, dims)
                result['operands'][name] = {'artifact': binding['artifact'], 'locator': binding['locator'],
                                            'source_value': values, 'unit': unit, 'unit_check': unit_check,
                                            'unit_basis': binding['unit_basis']}
            computed = expression_value(claim['expression'], operands)
            target = claim['unit']
            if target not in units or computed.dimensions != units[target][0]:
                raise ValueError('Expression dimensions do not match the claim unit')
            expected = finite_number(computed.value / units[target][1], 'converted result')
            asserted = finite_number(claim['value'], 'asserted claim value')
            tolerance = claim['tolerance']
            absolute = finite_number(tolerance['absolute'], 'absolute tolerance')
            relative = finite_number(tolerance['relative'], 'relative tolerance')
            if min(absolute, relative) < 0:
                raise ValueError('Tolerances cannot be negative')
            error = finite_number(abs(asserted-expected), 'absolute error')
            allowed = finite_number(absolute+relative*abs(expected), 'combined tolerance')
            result.update(status='passed' if error <= allowed else 'mismatch', expression=claim['expression'],
                          asserted_value=asserted, recomputed_value=expected, unit=target,
                          absolute_error=error, allowed_error=allowed, tolerance=tolerance,
                          arithmetic_verified=error <= allowed)
        except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError, SyntaxError, OSError) as exc:
            result.update(status='failed', reason=str(exc), arithmetic_verified=False)
        results.append(result)
    for identity, path in paths.items():
        if not path.is_file() or sha256(path) != bundle['artifacts'][identity]['sha256']:
            artifact_results[identity] = {'integrity': 'failed', 'reason': 'Artifact changed during verification'}
            for claim, result in zip(bundle['claims'], results):
                if any(b.get('artifact') == identity for b in claim.get('operands', {}).values()):
                    result.update(status='failed', reason='Operand artifact changed during verification', arithmetic_verified=False)
    return {'schema_version': 1, 'artifacts': artifact_results, 'claims': results,
            'all_arithmetic_checked': bool(results) and all(r['status'] == 'passed' for r in results),
            'scope': 'Hashes, locations, declared unit algebra and arithmetic only. Meaning, population selection, completeness of claim mapping and causal truth require review.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = Path(args.request).resolve()
    bundle = read_json(source)
    paths = [(source.parent/spec['path']).resolve() for spec in bundle['artifacts'].values()]
    ensure_output_safe(args.output, [source]+paths, '.json')
    result = verify(bundle, source.parent)
    result['provenance'] = provenance(source, [p for p in paths if p.is_file()], [__file__, Path(__file__).with_name('common.py'), Path(__file__).with_name('investigation_io.py')])
    write_json(args.output, result, inputs=[source]+paths)
    return 2 if any(r['status'] in {'failed', 'mismatch'} for r in result['claims']) or any(r['integrity'] == 'failed' for r in result['artifacts'].values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())

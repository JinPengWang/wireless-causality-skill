"""Configured association, predictive and paired-design investigations, with failures retained."""
import math
from collections import Counter, defaultdict
from common import finite_number, known_identity, require_keys


class Unsupported(ValueError):
    """Data or design does not support this particular backend."""


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value.startswith(('REPLACE_', 'TODO')):
        raise ValueError('Provide ' + label)
    return value


def integer(value, label, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(label + ' must be an integer >= ' + str(minimum))
    return value


def load_rows(data):
    if type(data.get('schema_version')) is not int or data.get('schema_version') != 1 or not isinstance(data.get('records'), list) or not data['records']:
        raise ValueError('Provide schema_version=1 and nonempty normalized records')
    records, seen, units = [], set(), {}
    for index, original in enumerate(data['records']):
        row = dict(original)
        if not known_identity(row.get('recording_id')):
            raise ValueError('Declare the recording identity')
        if not known_identity(row.get('unit_id')):
            row['unit_id'] = None
        if not isinstance(row.get('values'), dict):
            raise ValueError('Each record needs a values mapping')
        row['values'] = dict(row['values'])
        row['time_s'] = finite_number(row.get('time_s'), 'record time_s')
        identity = (row['recording_id'], row['time_s'])
        if identity in seen:
            raise ValueError('Duplicate recording timestamp; reconcile in the adapter')
        seen.add(identity)
        if units.setdefault(row['recording_id'], row['unit_id']) != row['unit_id']:
            raise ValueError('A recording cannot change independent unit')
        row['_row_index'] = index
        records.append(row)
    return sorted(records, key=lambda r: (r['recording_id'], r['time_s']))


def prepare(request, task, rows):
    variables = request['variables']
    selected = [task['outcome'], task['exposure']] + task['controls']
    if len(set(selected)) != len(selected):
        raise ValueError('Outcome, exposure and control names must be distinct')
    for name in selected:
        if name not in variables:
            raise ValueError('Undeclared variable: ' + name)
        spec = variables[name]
        for key in ['meaning', 'unit', 'time_scale', 'role']:
            text(spec.get(key), name + '.' + key)
        if not isinstance(spec.get('derived_from', []), list):
            raise ValueError('derived_from must be a list')
    def ancestors(name, trail=()):
        if name in trail:
            raise ValueError('Cyclic variable derivation')
        result = set()
        for parent in variables[name].get('derived_from', []):
            if parent not in variables:
                raise ValueError('Undeclared derivation parent: ' + parent)
            result.add(parent)
            result |= ancestors(parent, trail + (name,))
        return result
    for name in selected:
        if ancestors(name) & (set(selected) - {name}):
            raise Unsupported('Selected variables have a declared deterministic derivation; do not infer a new causal relation')
    reasons = task.get('control_rationale', {})
    for control in task['controls']:
        text(reasons.get(control), 'control rationale for ' + control)
        if variables[control]['role'] in {'mediator', 'collider', 'post_treatment', 'outcome'}:
            raise Unsupported('Bundled adjustment does not support control role: ' + variables[control]['role'])
    for key in ['question', 'scope', 'independent_unit_definition', 'observation_weighting']:
        text(request.get(key), key)
    if request['observation_weighting'] != 'equal_rows_within_recording':
        raise Unsupported('These backends require reviewed equal-row weighting; adapt other estimands explicitly')
    if not isinstance(task.get('assumptions'), list) or not task['assumptions']:
        raise ValueError('State applicable model/design assumptions')
    for assumption in task['assumptions']:
        text(assumption, 'assumption')
    for row in rows:
        for name in selected:
            value = row['values'].get(name)
            if value is not None:
                row['values'][name] = finite_number(value, 'value ' + name)
    return selected


def grouped(rows):
    result = defaultdict(list)
    for row in rows:
        result[row['recording_id']].append(row)
    return result


def fit(features, outcome):
    import numpy as np
    x = np.column_stack([np.ones(len(features)), np.asarray(features, dtype=float)])
    y = np.asarray(outcome, dtype=float)
    if len(y) <= x.shape[1]:
        raise Unsupported('Too few complete observations for the specified design matrix')
    beta, _, rank, singular = np.linalg.lstsq(x, y, rcond=None)
    if rank != x.shape[1]:
        raise Unsupported('Rank-deficient model; no separate coefficient is estimable')
    residual = y - x @ beta
    if not np.isfinite(beta).all() or not np.isfinite(residual).all():
        raise ValueError('Non-finite fitted result')
    diagnostics = {'n': len(y), 'parameters': x.shape[1], 'rank': int(rank),
                   'condition_number': float(singular[0] / singular[-1]),
                   'residual_rmse': float(np.max(np.abs(residual))*np.sqrt(np.mean((residual/np.max(np.abs(residual)))**2))) if np.any(residual) else 0.,
                   'residual_lag1_correlation': None}
    normalized = residual / np.max(np.abs(residual)) if np.any(residual) else residual
    if len(normalized) > 2 and np.std(normalized[:-1]) > 0 and np.std(normalized[1:]) > 0:
        diagnostics['residual_lag1_correlation'] = float(np.corrcoef(normalized[:-1], normalized[1:])[0, 1])
    for key, value in diagnostics.items():
        if value is not None:
            finite_number(value, 'model diagnostic ' + key)
    return beta, diagnostics


def summarize_units(items, value_key):
    import numpy as np
    by_unit = defaultdict(list)
    for item in items:
        if item.get('status') == 'executed' and known_identity(item.get('unit_id')):
            by_unit[item['unit_id']].append(item[value_key])
    values = [{'unit_id': unit, 'value': float(np.mean(v)), 'recordings': len(v)} for unit, v in sorted(by_unit.items())]
    estimates = [x['value'] for x in values]
    mean = float(np.mean(estimates)) if estimates else None
    influence = [{'omitted_unit': row['unit_id'], 'estimate': float(np.mean([v['value'] for v in values if v != row]))}
                 for row in values] if len(values) > 1 else []
    return {'n_independent_units': len(values), 'unknown_unit_recordings': [x.get('recording_id') for x in items if not known_identity(x.get('unit_id'))], 'unit_values': values, 'equal_unit_mean': mean,
            'min_unit_value': min(estimates) if estimates else None, 'max_unit_value': max(estimates) if estimates else None,
            'leave_one_unit_out': influence, 'uncertainty': 'No window-iid standard errors or causal probability computed.'}


def association(request, task, rows):
    names = [task['exposure']] + task['controls']
    yname = task['outcome']
    results = []
    for recording, sample in sorted(grouped(rows).items()):
        valid = [r for r in sample if all(r['values'].get(k) is not None for k in names + [yname])]
        result = {'recording_id': recording, 'unit_id': sample[0]['unit_id'],
                  'included_rows': [r['_row_index'] for r in valid],
                  'excluded_rows': [r['_row_index'] for r in sample if r not in valid]}
        try:
            beta, diagnostics = fit([[r['values'][n] for n in names] for r in valid], [r['values'][yname] for r in valid])
            result.update(status='executed', coefficient=float(beta[1]),
                          coefficients=dict(zip(['intercept'] + names, map(float, beta))), diagnostics=diagnostics)
        except Unsupported as exc:
            result.update(status='unsupported', reason=str(exc))
        except Exception as exc:
            result.update(status='failed', error_type=type(exc).__name__, reason=str(exc))
        results.append(result)
    return {'claim_type': 'association', 'recordings': results, 'summary': summarize_units(results, 'coefficient'),
            'coefficient_unit': request['variables'][yname]['unit'] + ' / ' + request['variables'][task['exposure']]['unit'],
            'validation': {'status': 'executed', 'kind': 'per-recording fit, heterogeneity and leave-one-unit-out influence',
                           'out_of_sample_prediction': 'not_requested'},
            'limitations': ['Linear conditional association, not intervention effect.',
                            'Complete-case selection and an asserted control set do not establish exchangeability.',
                            'Residual lag1 correlation is descriptive across retained adjacent observations; inspect gaps.']}


def prediction(request, task, rows):
    import numpy as np
    config = task.get('prediction', {})
    require_keys(config, ['step_s','lag_steps','train_fraction','min_test_rows'], ['step_s','lag_steps','train_fraction','min_test_rows','gap_steps'], 'prediction configuration')
    step = finite_number(config.get('step_s'), 'prediction step_s', positive=True)
    lag = integer(config.get('lag_steps'), 'lag_steps')
    fraction = finite_number(config.get('train_fraction'), 'train_fraction')
    if not 0 < fraction < 1:
        raise ValueError('train_fraction must lie strictly between 0 and 1')
    gap = integer(config.get('gap_steps', lag), 'gap_steps', minimum=lag)
    min_test = integer(config.get('min_test_rows'), 'min_test_rows')
    units, results = {}, []
    for recording, sample in sorted(grouped(rows).items()):
        result = {'recording_id': recording, 'unit_id': sample[0]['unit_id']}
        try:
            if any(not math.isclose(b['time_s'] - a['time_s'], step, rel_tol=1e-7, abs_tol=step * 1e-9)
                   for a, b in zip(sample, sample[1:])):
                raise Unsupported('Predictive backend requires a regular grid within each recording; no automatic resampling')
            examples = []
            for i in range(lag, len(sample)):
                past, current = sample[i-lag], sample[i]
                base = [past['values'].get(task['outcome'])] + [past['values'].get(k) for k in task['controls']]
                x, y = past['values'].get(task['exposure']), current['values'].get(task['outcome'])
                if any(v is None for v in base + [x, y]):
                    continue
                examples.append((i, base, base + [x], y, current['_row_index']))
            cutoff = int(len(sample) * fraction)
            train = [v for v in examples if v[0] < cutoff]
            test = [v for v in examples if v[0] >= cutoff + gap]
            if len(test) < min_test:
                raise Unsupported('Too few held-out rows after the temporal gap')
            b0, d0 = fit([v[1] for v in train], [v[3] for v in train])
            b1, d1 = fit([v[2] for v in train], [v[3] for v in train])
            def mse(beta, which):
                design = np.column_stack([np.ones(len(test)), np.array([v[which] for v in test])])
                return finite_number(float(np.mean((np.array([v[3] for v in test]) - design @ beta) ** 2)), 'held-out MSE; rescale through a reviewed unit mapping if necessary')
            mse0, mse1 = mse(b0, 1), mse(b1, 2)
            result.update(status='executed', train_rows=[v[4] for v in train], test_rows=[v[4] for v in test],
                          excluded_or_gap_rows=[r['_row_index'] for r in sample if r['_row_index'] not in {v[4] for v in train + test}],
                          baseline_mse=mse0, expanded_mse=mse1, delta_mse=mse0-mse1,
                          training_diagnostics={'baseline': d0, 'expanded': d1})
            units[recording] = (sample[0]['unit_id'], examples)
        except Unsupported as exc:
            result.update(status='unsupported', reason=str(exc))
        except Exception as exc:
            result.update(status='failed', error_type=type(exc).__name__, reason=str(exc))
        results.append(result)
    # Independent-unit holdout trains on other recordings, never joins their time axes.
    heldout = []
    for unit in sorted({u for u, _ in units.values() if known_identity(u)}):
        training = [v for u, examples in units.values() if known_identity(u) and u != unit for v in examples]
        entry = {'unit_id': unit, 'training_units': sorted({u for u, _ in units.values() if known_identity(u) and u != unit})}
        try:
            b0, _ = fit([v[1] for v in training], [v[3] for v in training])
            b1, _ = fit([v[2] for v in training], [v[3] for v in training])
            scores = []
            for recording, (u, examples) in units.items():
                if u != unit:
                    continue
                y = np.asarray([v[3] for v in examples])
                errors = [finite_number(float(np.mean((y - np.column_stack([np.ones(len(y)), np.array([v[col] for v in examples])]) @ b) ** 2)), 'held-out-unit MSE')
                          for b, col in [(b0, 1), (b1, 2)]]
                scores.append({'recording_id': recording, 'delta_mse': errors[0]-errors[1], 'test_rows': [v[4] for v in examples]})
            entry.update(status='executed', recordings=scores)
        except Unsupported as exc:
            entry.update(status='unsupported', reason=str(exc))
        except Exception as exc:
            entry.update(status='failed', error_type=type(exc).__name__, reason=str(exc))
        heldout.append(entry)
    if not heldout:
        heldout.append({'status': 'unsupported', 'reason': 'Independent-unit holdout needs known independent units and usable recordings'})
    uncertainty = request.get('relative_clock_uncertainty_s')
    if uncertainty is not None:
        uncertainty = finite_number(uncertainty, 'relative_clock_uncertainty_s')
        if uncertainty < 0:
            raise ValueError('Clock uncertainty cannot be negative')
    return {'claim_type': 'incremental_prediction', 'recordings': results, 'summary': summarize_units(results, 'delta_mse'),
            'held_out_units': heldout, 'nominal_lag_s': step * lag,
            'timing_interpretation': 'not_resolved' if uncertainty is None or uncertainty >= step * lag else 'clock_bound_declared',
            'validation': {'status': 'executed' if all(r['status']=='executed' for r in results+heldout) else 'partial',
                           'kind': 'forward temporal holdout with gap and leave-one-independent-unit-out',
                           'temporal_holdout_statuses': dict(Counter(r['status'] for r in results)),
                           'unit_holdout_statuses': dict(Counter(r['status'] for r in heldout))},
            'limitations': ['Positive delta MSE is incremental predictive information, not causation or a physical response delay.',
                            'Models and lags must be fixed before validation; selection on these scores needs a new outer holdout.',
                            'Cross-unit fits weight training rows equally; testing reports every recording without pooling units.']}


def paired_contrast(request, task, rows):
    import itertools
    import numpy as np
    if any(not known_identity(r['unit_id']) for r in rows):
        raise Unsupported('Paired comparison needs actual independent pair identities; per-recording association remains available')
    xname, yname = task['exposure'], task['outcome']
    recordings, by_unit = [], defaultdict(lambda: {0: [], 1: []})
    for recording, sample in sorted(grouped(rows).items()):
        treatments = {r['values'].get(xname) for r in sample}
        result = {'recording_id': recording, 'unit_id': sample[0]['unit_id'], 'n_rows': len(sample)}
        valid = [r for r in sample if r['values'].get(yname) is not None]
        if len(treatments) != 1 or not treatments <= {0, 1} or not valid:
            result.update(status='unsupported', reason='Need a constant binary assigned exposure and observed outcome per recording')
        else:
            treatment = int(next(iter(treatments)))
            result.update(status='executed', treatment=treatment, mean=float(np.mean([r['values'][yname] for r in valid])),
                          included_rows=[r['_row_index'] for r in valid],
                          excluded_rows=[r['_row_index'] for r in sample if r not in valid])
            by_unit[result['unit_id']][treatment].append(result)
        recordings.append(result)
    pairs, excluded = [], []
    for unit in sorted({r['unit_id'] for r in rows}):
        conditions = by_unit[unit]
        unit_rows = [r for r in rows if r['unit_id'] == unit]
        if any(len({r['values'].get(c) for r in unit_rows}) != 1 or unit_rows[0]['values'].get(c) is None for c in task['controls']):
            excluded.append({'unit_id': unit, 'reason': 'Matched controls are missing or vary within the independent pair'})
        elif not conditions[0] or not conditions[1]:
            excluded.append({'unit_id': unit, 'reason': 'Missing an observed control or exposed recording'})
        else:
            control = float(np.mean([r['mean'] for r in conditions[0]]))
            exposed = float(np.mean([r['mean'] for r in conditions[1]]))
            pairs.append({'unit_id': unit, 'status': 'executed', 'control_mean': control, 'exposed_mean': exposed,
                          'difference': exposed-control, 'recording_ids': [r['recording_id'] for group in conditions.values() for r in group]})
    design = task.get('design', {'type': 'observational_paired'})
    kind = design.get('type')
    if kind not in {'observational_paired', 'randomized_paired'}:
        raise Unsupported('Choose another backend for this identification design')
    summary = summarize_units(pairs, 'difference')
    p_value = None
    inference = {'status': 'not_identified', 'reason': 'Observed matched contrast does not establish exchangeability.'}
    if kind == 'randomized_paired':
        for key in ['assignment_evidence', 'estimand', 'population', 'time_horizon', 'carryover_assessment', 'interference_assessment', 'missingness_assessment']:
            text(design.get(key), 'randomized design ' + key)
        if design.get('assignment_unit') != 'independent_pair':
            raise Unsupported('Exact paired randomization requires one exchangeable label swap per independent pair')
        differences = [r['difference'] for r in pairs]
        if not 2 <= len(differences) <= 16:
            inference = {'status': 'unsupported', 'reason': 'Exact randomization backend supports 2..16 independent pairs; no silent approximation.'}
        else:
            observed = abs(float(np.mean(differences)))
            extreme = sum(abs(float(np.mean(np.asarray(differences)*signs))) >= observed*(1-1e-12)
                          for signs in itertools.product([-1, 1], repeat=len(differences)))
            p_value = extreme / (2 ** len(differences))
            inference = {'status': 'executed', 'method': 'exact independent-pair sign randomization',
                         'null': 'Sharp null of no treatment effect under the declared paired assignment',
                         'two_sided_statistic': 'absolute equal-pair mean difference', 'permutations': 2 ** len(differences),
                         'identification': 'conditional_on_declared_design', 'assumptions_verified_by_software': False}
    return {'claim_type': 'intervention_effect' if inference['status'] == 'executed' else 'association',
            'recordings': recordings, 'pairs': pairs, 'excluded_units': excluded, 'summary': summary,
            'design': design, 'inference': inference, 'p_value': p_value,
            'validation': {'status': 'executed', 'kind': 'per-recording summaries, pair heterogeneity and leave-one-pair-out influence'},
            'limitations': ['Independent pair identities and assignment evidence need substantive review.',
                            'No causal conclusion from matching alone; complete-case pair selection can change the target population.',
                            'Equal rows within recordings, equal recordings within conditions, equal independent pairs.']}


BACKENDS = {'adjusted_association': association, 'lagged_prediction': prediction, 'paired_contrast': paired_contrast}


def analyze(request, data):
    require_keys(request, ['schema_version', 'question', 'scope', 'independent_unit_definition', 'observation_weighting', 'variables', 'analyses', 'multiplicity'],
                 ['schema_version', 'question', 'scope', 'data', 'independent_unit_definition', 'observation_weighting', 'variables',
                  'analyses', 'multiplicity', 'relative_clock_uncertainty_s'], 'causal investigation request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('Unsupported causal request schema')
    rows = load_rows(data)
    tasks = request['analyses']
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('Provide analysis tasks')
    ids = [text(t.get('id'), 'analysis id') for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValueError('Analysis ids must be unique')
    results = []
    for task in tasks:
        output = {'id': task['id'], 'requested_method': task.get('method'), 'configuration': task, 'attempts': []}
        try:
            require_keys(task, ['id', 'method', 'outcome', 'exposure', 'controls', 'assumptions'],
                         ['id', 'method', 'outcome', 'exposure', 'controls', 'assumptions', 'control_rationale',
                          'mode', 'prediction', 'design', 'fallback'], 'analysis task')
            if not isinstance(task['controls'], list):
                raise ValueError('controls must be an explicit list, including when empty')
            if task.get('mode', 'execute') not in {'execute', 'plan'}:
                raise ValueError('mode must be execute or plan')
            if task.get('mode') == 'plan':
                output.update(status='planned', reason='Not executed by request')
                results.append(output)
                continue
            prepare(request, task, rows)
            for method in [task['method']] + ([task['fallback']] if task.get('fallback') else []):
                try:
                    if method not in BACKENDS:
                        raise Unsupported('Backend is not implemented here: ' + str(method))
                    result = BACKENDS[method](request, task, rows)
                    count = Counter(r['status'] for r in result['recordings'])
                    status = 'executed' if count['executed'] == len(result['recordings']) else ('partial' if count['executed'] else ('failed' if count['failed'] else 'unsupported'))
                    if result.get('held_out_units') and any(r['status'] != 'executed' for r in result['held_out_units']):
                        status = 'partial' if count['executed'] else ('failed' if count['failed'] else 'unsupported')
                    if result.get('excluded_units') or result.get('inference', {}).get('status') == 'unsupported':
                        status = 'partial' if count['executed'] else ('failed' if count['failed'] else 'unsupported')
                    if method == 'paired_contrast' and not result['pairs']:
                        status = 'unsupported'
                    output.update(status=status, method=method, result=result)
                    output['attempts'].append({'method': method, 'status': status, 'result': result} if status == 'unsupported' else {'method': method, 'status': status})
                    if status == 'unsupported' and method != task.get('fallback') and task.get('fallback'):
                        continue
                    break
                except (Unsupported, ImportError) as exc:
                    output['attempts'].append({'method': method, 'status': 'unsupported', 'reason': str(exc)})
            if 'status' not in output:
                output.update(status='unsupported', reason=output['attempts'][-1]['reason'])
        except Unsupported as exc:
            output.update(status='unsupported', reason=str(exc))
        except Exception as exc:
            output.update(status='failed', error_type=type(exc).__name__, reason=str(exc))
        results.append(output)
    multiplicity = request['multiplicity']
    method = multiplicity.get('method')
    if method not in {'none', 'holm'}:
        raise ValueError('Multiplicity method must be none or holm')
    text(multiplicity.get('rationale'), 'multiplicity rationale')
    families = multiplicity.get('families', {})
    covered = []
    for family, members in families.items():
        text(family, 'family name')
        if not members or not isinstance(members, list) or any(m not in ids for m in members):
            raise ValueError('A test family must declare known analysis ids')
        covered += members
    if len(covered) != len(set(covered)):
        raise ValueError('Declare disjoint test families; do not duplicate tests')
    tested = {r['id']: r for r in results if r.get('result', {}).get('p_value') is not None}
    if tested.keys() - set(covered):
        raise ValueError('Every computed p-value needs a declared test family')
    corrections = []
    for family, members in families.items():
        ordered = sorted((tested[m]['result']['p_value'] if m in tested else 1., m) for m in members)
        running = 0.
        for index, (p, identity) in enumerate(ordered):
            running = max(running, min(1., (len(members)-index)*p))
            corrections.append({'family': family, 'analysis_id': identity, 'p_value': p if identity in tested else None,
                                'adjusted_p_value': running if method == 'holm' and identity in tested else None,
                                'status': 'executed' if identity in tested else 'not_tested',
                                'family_size': len(members)})
    return {'schema_version': 1, 'question': request['question'], 'scope': request['scope'],
            'configuration': request, 'n_recordings': len(grouped(rows)),
            'n_declared_independent_units': len({r['unit_id'] for r in rows if known_identity(r['unit_id'])}),
            'execution_summary': dict(Counter(r['status'] for r in results)), 'analyses': results,
            'has_execution_failures': any(r['status']=='failed' or any(v['status']=='failed' for k in ['recordings','held_out_units'] for v in r.get('result',{}).get(k,[])) for r in results),
            'multiplicity': {'configuration': multiplicity, 'results': corrections,
                             'untested_policy': 'Retain declared family size with conservative p=1 placeholders, never claim they were tested.'},
            'question_answer_status': 'requires_interpretation', 'delivery_quality_status': 'not_checked',
            'causal_truth_verified': False}


if __name__ == '__main__':
    from investigation_io import run_analysis_cli
    result = run_analysis_cli(analyze, __file__, __doc__)
    raise SystemExit(2 if result['has_execution_failures'] else 0)

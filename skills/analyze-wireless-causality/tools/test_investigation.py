"""Synthetic scientific and evidence-contract regression tests; no private recordings."""
import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import openpyxl
from common import read_json, sha256, write_json
from causal_analysis import analyze as causal
from event_analysis import analyze as events
from verify_claims import verify, expression_value, Quantity
from evidence_model import validate_evidence
from write_report import render
from investigation_io import snapshot_json, run_analysis_cli


def causal_fixture(method='adjusted_association', units=3):
    rng = np.random.default_rng(41)
    rows = []
    for unit in range(units):
        for i in range(80):
            x, c = rng.normal(size=2)
            rows.append({'recording_id': 'rec'+str(unit), 'unit_id': 'independent'+str(unit),
                         'time_s': .2*i, 'values': {'signal': x, 'context': c, 'outcome': 2*x+3*c}})
    variables = {k: {'meaning': 'Synthetic '+k, 'unit': '1', 'time_scale': 'per observation',
                     'role': 'pre_exposure' if k == 'context' else 'measurement', 'derived_from': []}
                 for k in ['signal', 'context', 'outcome']}
    task = {'id': 'A', 'method': method, 'outcome': 'outcome', 'exposure': 'signal', 'controls': ['context'],
            'control_rationale': {'context': 'Known synthetic common input'},
            'assumptions': ['Declared independent units and linear conditional relation within recordings']}
    request = {'schema_version': 1, 'question': 'Compare conditional relationships', 'scope': 'Synthetic population',
               'independent_unit_definition': 'Separately generated sessions',
               'observation_weighting': 'equal_rows_within_recording', 'variables': variables,
               'analyses': [task], 'multiplicity': {'method': 'none', 'rationale': 'No inferential p-values requested', 'families': {}}}
    return request, {'schema_version': 1, 'records': rows}


def paired_fixture(scale=1.):
    request, data = causal_fixture('paired_contrast')
    data['records'] = []
    for unit in range(3):
        for exposure in [0, 1]:
            for i in range(5):
                data['records'].append({'recording_id': f'r{unit}_{exposure}', 'unit_id': f'p{unit}', 'time_s': i,
                                        'values': {'signal': exposure, 'outcome': (unit+exposure)*scale, 'context': unit}})
    request['analyses'][0]['design'] = {
        'type': 'randomized_paired', 'assignment_unit': 'independent_pair',
        **{k:'Synthetic randomized design' for k in ['assignment_evidence','estimand','population','time_horizon',
                                                    'carryover_assessment','interference_assessment','missingness_assessment']}}
    request['multiplicity'] = {'method': 'holm', 'rationale': 'Declared family', 'families': {'primary':['A']}}
    return request, data


def event_fixture(offset=0.):
    rows = []
    for start, end, value in [(-2,-1,10),(-1,0,10),(0,1,10),(1,1.5,1),(2,2.5,1),(2.5,3,10)]:
        rows.append({'run_id':'r','entity':'e','direction':'outbound','condition':'fixed','pair_id':'u',
                     'metric':'rate','unit':'bit/s','start_s':start+offset,'end_s':end+offset,'coverage':1.,
                     'value':value,'definition':'synthetic interval rate','kind':'interval_mean'})
    request = {'schema_version':1,'pre_interval_s':[-2,0],'post_interval_s':[0,3],
               'events':[{'id':'event','unit_id':'u','anchor_s':offset,'anchor_uncertainty_s':0.,
                          'origin':'external','evidence':'Synthetic external annotation','recordings':{'radio':'r'}}],
               'signals':[{'id':'radio','layer':'wireless','metric':'rate','relative_clock_uncertainty_s':0.,
                           'threshold':5,'bad_direction':'below','hold_s':1.}]}
    return request, {'windows':rows}


class BackendTests(unittest.TestCase):
    def test_controlled_coefficient_and_units(self):
        q,d=causal_fixture();r=causal(q,d)['analyses'][0]
        self.assertEqual(r['status'],'executed')
        self.assertAlmostEqual(r['result']['summary']['equal_unit_mean'],2.)
        self.assertEqual(r['result']['summary']['n_independent_units'],3)
        self.assertEqual(len(r['result']['recordings']),3)
    def test_shared_session_is_not_two_independent_units(self):
        q,d=causal_fixture(units=2)
        for row in d['records']:row['unit_id']='same'
        self.assertEqual(causal(q,d)['analyses'][0]['result']['summary']['n_independent_units'],1)
    def test_unknown_units_still_allow_per_recording_exploration(self):
        q,d=causal_fixture(units=1)
        for row in d['records']:row['unit_id']=None
        r=causal(q,d)['analyses'][0]
        self.assertEqual(r['status'],'executed');self.assertEqual(r['result']['summary']['n_independent_units'],0)
        self.assertAlmostEqual(r['result']['recordings'][0]['coefficient'],2)
    def test_missing_recording_is_retained(self):
        q,d=causal_fixture(units=2)
        for row in d['records'][80:]:row['values']['outcome']=None
        r=causal(q,d)['analyses'][0]
        self.assertEqual(r['status'],'partial');self.assertEqual(r['result']['recordings'][1]['status'],'unsupported')
    def test_deterministic_variable_not_new_cause(self):
        q,d=causal_fixture();q['variables']['outcome']['derived_from']=['signal']
        self.assertEqual(causal(q,d)['analyses'][0]['status'],'unsupported')
    def test_mediator_not_silently_used_as_adjustment(self):
        q,d=causal_fixture();q['variables']['context']['role']='mediator'
        self.assertEqual(causal(q,d)['analyses'][0]['status'],'unsupported')
    def test_unavailable_backend_explicit_fallback(self):
        q,d=causal_fixture();q['analyses'][0].update(method='optional_backend_not_installed',fallback='adjusted_association')
        r=causal(q,d)['analyses'][0]
        self.assertEqual([a['status'] for a in r['attempts']],['unsupported','executed'])
    def test_planned_and_failed_tasks_do_not_hide_success(self):
        q,d=causal_fixture();q['analyses'] += [{**q['analyses'][0],'id':'P','mode':'plan'}, {**q['analyses'][0],'id':'F','contrls':[]}]
        r=causal(q,d);self.assertEqual(r['execution_summary'],{'executed':1,'planned':1,'failed':1})
    def test_exact_randomization_is_scale_invariant(self):
        for scale in [1.,1e-15,1e9]:
            q,d=paired_fixture(scale);r=causal(q,d)['analyses'][0]['result']
            self.assertAlmostEqual(r['p_value'],.25);self.assertEqual(r['claim_type'],'intervention_effect')
            self.assertFalse(r['inference']['assumptions_verified_by_software'])
    def test_observational_pair_has_no_intervention_pvalue(self):
        q,d=paired_fixture();q['analyses'][0]['design']={'type':'observational_paired'}
        r=causal(q,d)['analyses'][0]['result']
        self.assertIsNone(r['p_value']);self.assertEqual(r['inference']['status'],'not_identified')

    def test_unresolved_randomization_retains_differences_without_effect_label(self):
        fields = ['assignment_evidence', 'estimand', 'population', 'time_horizon',
                  'carryover_assessment', 'interference_assessment', 'missingness_assessment']
        for key, value in ([(key, 'unknown') for key in fields] + [
                ('assignment_evidence', None), ('assignment_evidence', ' 未知 '),
                ('assignment_evidence', 'Pair order was not randomized.'),
                ('assignment_evidence', '未随机分配，固定先后顺序'),
                ('assignment_evidence', 'Randomization: unknown'),
                ('assignment_evidence', 'Assignment method = not documented'),
                ('assignment_evidence', 'Non-random assignment; A was always measured before B.'),
                ('assignment_evidence', '未隨機分配，固定先 A 後 B。'),
                ('assignment_evidence', '隨機分配狀態：未知'),
                ('carryover_assessment', ' TBD: check later'), ('estimand', '不适用'),
                ('carryover_assessment', 'Not applicable: TBD'),
                ('carryover_assessment', 'Not applicable'),
                ('interference_assessment', 'TODO_CHECK_INTERFERENCE'),
                ('assignment_unit', 'recording'), ('assignment_status', 'unknown')]):
            with self.subTest(key=key, value=value):
                q, d = paired_fixture()
                design = q['analyses'][0]['design']
                if value is None:
                    del design[key]
                else:
                    design[key] = value
                report = causal(q, d)
                analysis = report['analyses'][0]
                result = analysis['result']
                self.assertEqual(analysis['status'], 'partial')
                self.assertEqual(result['summary']['equal_unit_mean'], 1.)
                self.assertEqual(result['claim_type'], 'association')
                self.assertEqual(result['inference']['status'], 'not_identified')
                self.assertIn(key, result['inference']['unresolved_fields'])
                self.assertIsNone(result['p_value'])
                self.assertEqual(report['multiplicity']['results'][0]['status'], 'not_tested')

    def test_documented_randomization_keeps_existing_exact_inference(self):
        q, d = paired_fixture()
        design = q['analyses'][0]['design']
        design.update(assignment_status='documented', assignment_evidence='Pair order was drawn using seeded RNG in log R1',
                      missingness_assessment='Missing outcomes were checked against the log; all assigned observations are present.')
        design['assignment_evidence'] += '; no evidence of randomization errors was found.'
        result = causal(q, d)['analyses'][0]['result']
        self.assertEqual(result['claim_type'], 'intervention_effect')
        self.assertEqual(result['p_value'], .25)

    def test_assessment_can_explain_why_a_risk_does_not_apply(self):
        for explanation in ('Not applicable: different devices in each pair received one condition each.',
                            '不適用：配對中的兩台設備各自只接受一種條件。'):
            with self.subTest(explanation=explanation):
                request, data = paired_fixture()
                request['analyses'][0]['design']['carryover_assessment'] = explanation
                result = causal(request, data)['analyses'][0]['result']
                self.assertEqual(result['claim_type'], 'intervention_effect')
                self.assertEqual(result['p_value'], .25)

    def test_holm_keeps_unexecuted_family_member(self):
        q,d=paired_fixture();q['analyses'].append({**q['analyses'][0],'id':'P','mode':'plan'})
        q['multiplicity']['families']['primary'].append('P')
        r=causal(q,d)['multiplicity']['results']
        self.assertEqual(next(v for v in r if v['analysis_id']=='A')['adjusted_p_value'],.5)
        self.assertEqual(next(v for v in r if v['analysis_id']=='P')['status'],'not_tested')
    def test_pair_control_mismatch_remains_visible(self):
        q,d=paired_fixture();d['records'][0]['values']['context']=99
        r=causal(q,d)['analyses'][0]
        self.assertEqual(r['status'],'partial');self.assertEqual(len(r['result']['excluded_units']),1)
    def test_incremental_prediction_has_temporal_and_unit_holdouts(self):
        q,d=causal_fixture('lagged_prediction');q['relative_clock_uncertainty_s']=None
        q['analyses'][0]['prediction']={'step_s':.2,'lag_steps':1,'train_fraction':.6,'gap_steps':2,'min_test_rows':5}
        for run in ['rec0','rec1','rec2']:
            rows=[r for r in d['records'] if r['recording_id']==run]
            for i in range(1,len(rows)):rows[i]['values']['outcome']=2*rows[i-1]['values']['signal']+.1*rows[i]['values']['context']
        r=causal(q,d)['analyses'][0]['result']
        self.assertGreater(r['summary']['equal_unit_mean'],0)
        self.assertEqual(r['claim_type'],'incremental_prediction');self.assertEqual(r['timing_interpretation'],'not_resolved')
        for entry in r['held_out_units']:self.assertNotIn(entry['unit_id'],entry['training_units'])
        for entry in r['recordings']:self.assertLess(max(entry['train_rows']),min(entry['test_rows'])-1)
    def test_irregular_grid_is_not_silently_resampled(self):
        q,d=causal_fixture('lagged_prediction',units=1)
        q['analyses'][0]['prediction']={'step_s':.2,'lag_steps':1,'train_fraction':.6,'min_test_rows':5}
        d['records'][20]['time_s']+=.01
        self.assertEqual(causal(q,d)['analyses'][0]['status'],'unsupported')

    def test_unit_holdout_can_score_unit_with_constant_exposure_and_accounts_for_missing_recordings(self):
        q, d = causal_fixture('lagged_prediction')
        q['analyses'][0]['prediction'] = {'step_s': .2, 'lag_steps': 1, 'train_fraction': .6, 'min_test_rows': 5}
        # Current outcomes must vary independently of the past features used in the fit.
        for i, row in enumerate(d['records']):
            row['values']['outcome'] += math.sin(i)
            if row['recording_id'] == 'rec2':
                row['values']['signal'] = 0
        for unit, recording in [('independent2', 'empty'), ('independent3', 'only-empty')]:
            d['records'].append({'recording_id': recording, 'unit_id': unit, 'time_s': 0, 'values': {}})
        result = causal(q, d)['analyses'][0]['result']
        temporal = {r['recording_id']: r['status'] for r in result['recordings']}
        units = {r['unit_id']: r for r in result['held_out_units']}
        self.assertEqual(temporal['rec2'], 'unsupported')
        self.assertEqual(units['independent2']['status'], 'partial')
        self.assertEqual(units['independent2']['training_units'], ['independent0', 'independent1'])
        self.assertEqual(units['independent2']['recordings'][0]['test_rows'], list(range(161, 240)))
        self.assertEqual(units['independent2']['excluded_recordings'][0]['recording_id'], 'empty')
        self.assertEqual(units['independent3']['status'], 'unsupported')
        self.assertTrue(units['independent3']['reason'])
        self.assertEqual(result['validation']['unit_holdout_statuses'], {'executed': 2, 'partial': 1, 'unsupported': 1})

    def test_unit_holdout_without_temporal_fit_still_returns_partial_execution(self):
        q, d = causal_fixture('lagged_prediction')
        q['analyses'][0]['prediction'] = {'step_s': .2, 'lag_steps': 1, 'train_fraction': .99, 'min_test_rows': 5}
        for i, row in enumerate(d['records']):
            row['values']['outcome'] += math.sin(i)
        analysis = causal(q, d)['analyses'][0]
        self.assertEqual(analysis['status'], 'partial')
        self.assertEqual(analysis['result']['validation']['temporal_holdout_statuses'], {'unsupported': 3})
        self.assertEqual(analysis['result']['validation']['unit_holdout_statuses'], {'executed': 3})
    def test_overflow_never_emits_nonfinite_json(self):
        q,d=causal_fixture(units=1)
        for i,row in enumerate(d['records']):row['values']['outcome']=1e200*(-1 if i%2 else 1)
        r=causal(q,d);json.dumps(r,allow_nan=False)
        self.assertEqual(r['analyses'][0]['status'],'executed');self.assertFalse(r['has_execution_failures'])
    def test_execution_failure_is_not_an_unsupported_design(self):
        q,d=causal_fixture()
        with patch('causal_analysis.fit',side_effect=FloatingPointError('Synthetic numerical failure')):
            r=causal(q,d)
        self.assertEqual(r['execution_summary'],{'failed':1});self.assertTrue(r['has_execution_failures'])
        self.assertEqual(len(r['analyses'][0]['result']['recordings']),3)
    def test_prediction_configuration_typo_is_rejected(self):
        q,d=causal_fixture('lagged_prediction')
        q['analyses'][0]['prediction']={'step_s':.2,'lag_steps':1,'train_fraction':.6,'min_test_rows':5,'lag_step':2}
        self.assertEqual(causal(q,d)['analyses'][0]['status'],'failed')
    def test_duplicate_timestamp_rejected(self):
        q,d=causal_fixture();d['records'].append(copy.deepcopy(d['records'][0]))
        with self.assertRaises(ValueError):causal(q,d)


class EventTests(unittest.TestCase):
    def test_gap_not_bridged_by_epoch_time_origin(self):
        for offset in [0.,1e9]:
            q,d=event_fixture(offset);r=events(q,d)['event_signal_results'][0]['response']
            self.assertEqual(r['status'],'not_observed_in_followup');self.assertTrue(r['gaps'])
    def test_straddling_interval_requires_explicit_allocation(self):
        q,d=event_fixture();d['windows']=[{**d['windows'][0],'start_s':-1,'end_s':1,'value':50}]
        q['pre_interval_s']=[-1,0];q['post_interval_s']=[0,1]
        r=events(q,d)['event_signal_results'][0]
        self.assertIsNone(r['delta']);self.assertEqual(r['pre']['excluded_boundary_windows'],[0])
        q['split_policy']='uniform';r=events(q,d)['event_signal_results'][0]
        self.assertEqual(r['delta'],0);self.assertEqual(r['pre']['within_window_allocation_assumption'],'uniform')
    def test_unknown_clock_never_reports_response_lag(self):
        q,d=event_fixture();q['signals'][0].update(relative_clock_uncertainty_s=None,hold_s=.4)
        r=events(q,d)['event_signal_results'][0]
        self.assertEqual(r['alignment_status'],'unknown');self.assertIsNone(r['response']['lag_bounds_s'])
    def test_numeric_uncertainty_is_not_string_concatenation(self):
        q,d=event_fixture();q['events'][0]['anchor_uncertainty_s']='1';q['signals'][0]['relative_clock_uncertainty_s']='2'
        self.assertEqual(events(q,d)['event_signal_results'][0]['combined_uncertainty_s'],3)
    def test_same_recording_cannot_gain_new_independent_identity(self):
        q,d=event_fixture();q['events'].append({**q['events'][0],'id':'other','unit_id':'other_unit'})
        with self.assertRaises(ValueError):events(q,d)
    def test_unmeasured_endpoint_layer_is_unsupported(self):
        q,d=event_fixture();q['signals'].append({'id':'endpoint','layer':'endpoint','metric':'cpu','relative_clock_uncertainty_s':None})
        r=events(q,d)['event_signal_results'][1]
        self.assertEqual(r['status'],'unsupported')
    def test_initial_missing_prefix_censors_timing(self):
        q,d=event_fixture();d['windows']=[{**d['windows'][0],'start_s':2,'end_s':3,'value':1}]
        r=events(q,d)['event_signal_results'][0]['response']
        self.assertTrue(r['left_or_gap_censored']);self.assertIsNone(r['lag_bounds_s'])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.parent=Path(tempfile.gettempdir())
        self.tmp=tempfile.TemporaryDirectory(dir=self.parent);self.root=Path(self.tmp.name)
    def tearDown(self):
        if self.root.resolve().parent != self.parent.resolve():raise RuntimeError('Unexpected cleanup path')
        self.tmp.cleanup()
    def bundle(self):
        path=self.root/'values.json';write_json(path,{'amount':[100,300],'duration':.2,'unit':'byte'})
        bundle={'schema_version':1,'artifacts':{'a':{'path':'values.json','sha256':sha256(path)}},'claims':[{
            'id':'C1','statement':'Rate equals 16 kbit/s under the declared byte-count definition',
            'operands':{
                'amount':{'artifact':'a','locator':{'type':'json_pointer','pointer':'/amount'},'unit':'byte',
                          'unit_locator':{'type':'json_pointer','pointer':'/unit'},'unit_basis':'Synthetic payload-byte measurement'},
                'duration':{'artifact':'a','locator':{'type':'json_pointer','pointer':'/duration'},'unit':'s','unit_basis':'Synthetic observation exposure'}},
            'expression':'sum(amount)/duration','value':16.,'unit':'kbit/s','tolerance':{'absolute':1e-12,'relative':0.}}]}
        return bundle
    def ledger(self):
        bundle=self.bundle();config=self.root/'config.json';write_json(config,{'description':'Synthetic contract'})
        return {'schema_version':3,'analysis_status':'completed','language':'zh-CN','title':'合成证据检查',
                'question':'检查明确字段的计算','scope':'合成测试','measurement_contract':'字节总量除以观测时长',
                'phenomena':[{'id':'P1','statement':'计算速率为 16 kbit/s','status':'observed','calculation':'sum(amount)/duration',
                              'evidence':[{'path':'values.json','sha256':sha256(self.root/'values.json'),
                                           'locator':{'type':'json_pointer','pointer':'/amount'},'supports':'字节计数输入'}],
                              'figures':[],'limitations':'仅验证合成输入','claim_ids':['C1']}],
                'findings':[],'limitations':'不涉及真实因果结论','reproduce':'Run the synthetic unittest fixture',
                'numeric_claims':bundle,
                'assessment':{'execution':{'status':'completed','reason':'Synthetic calculation executed'},
                              'data_capability':{'status':'sufficient','reason':'Inputs explicitly known'},
                              'question_answer':{'status':'answered','reason':'Arithmetic-only question'},
                              'delivery_quality':{'status':'partial','reason':'No visual review requested',
                                                  'checks':[{'id':'arithmetic','status':'passed','reason':'Recomputed fixture'}]}},
                'claim_review':{'status':'passed','reviewer':'Synthetic fixture','note':'One atomic numerical statement mapped', 'unmapped_statements':[]},
                'provenance':{'skill_revision':'synthetic-test-fixture','runtime':{'executable':sys.executable,'python':sys.version,'packages':{'numpy':np.__version__}},
                              'commands':[[sys.executable,'-m','unittest','discover','-s','tools']],
                              'artifacts':[{'role':'source','path':'values.json','sha256':sha256(self.root/'values.json')},
                                           {'role':'configuration','path':'config.json','sha256':sha256(config)},
                                           {'role':'tool','path':str(Path(__file__).resolve()),'sha256':sha256(__file__)}]}}
    def test_units_and_formula_recomputed(self):
        r=verify(self.bundle(),self.root)['claims'][0]
        self.assertEqual(r['status'],'passed');self.assertEqual(r['recomputed_value'],16.)
        self.assertFalse(r['meaning_verified']);self.assertFalse(r['causal_truth_verified'])
    def test_incorrect_assertion_is_mismatch(self):
        q=self.bundle();q['claims'][0]['value']=20
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'mismatch')
    def test_wrong_dimensions_fail(self):
        q=self.bundle();q['claims'][0]['unit']='byte'
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_wrong_artifact_unit_fails(self):
        q=self.bundle();q['claims'][0]['operands']['amount']['unit']='bit'
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_wrong_json_pointer_fails(self):
        q=self.bundle();q['claims'][0]['operands']['amount']['locator']['pointer']='/missing'
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_changed_hash_fails(self):
        q=self.bundle();(self.root/'values.json').write_text('{}')
        self.assertEqual(verify(q,self.root)['artifacts']['a']['integrity'],'failed')
    def test_constant_expression_cannot_hide_unused_evidence(self):
        q=self.bundle();q['claims'][0]['expression']='16'
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_expression_cannot_execute_code(self):
        q=self.bundle();q['claims'][0]['expression']="__import__('os').getcwd() + sum(amount)/duration"
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_large_integer_loss_is_not_certified(self):
        q=self.bundle();path=self.root/'values.json';write_json(path,{'amount':[9007199254740993],'duration':1,'unit':'byte'})
        q['artifacts']['a']['sha256']=sha256(path);q['claims'][0].update(expression='sum(amount)',value=9007199254740992,unit='byte')
        q['claims'][0]['operands'].pop('duration');q['claims'][0]['tolerance']={'absolute':0,'relative':0}
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')

    def test_integer_intermediate_cancellation_cannot_pass_a_zero_tolerance_claim(self):
        q = self.bundle()
        path = self.root/'values.json'
        boundary = 2**53
        write_json(path, {'x': 1, 'v': [boundary, 1]})
        q['artifacts']['a']['sha256'] = sha256(path)
        claim = q['claims'][0]
        for expression, field in [(f'{boundary} + x - {boundary}', 'x'), (f'sum(x) - {boundary}', 'v'),
                                  (f'({boundary} * 2 + x) - {boundary} * 2', 'x')]:
            with self.subTest(expression=expression):
                claim.update(expression=expression, value=0, unit='1', tolerance={'absolute': 0, 'relative': 0},
                             operands={'x': {'artifact': 'a', 'locator': {'type': 'json_pointer', 'pointer': '/'+field},
                                             'unit': '1', 'unit_basis': 'Synthetic count'}})
                check = verify(q, self.root)['claims'][0]
                self.assertEqual(check['status'], 'failed')
                self.assertIn('integer intermediate', check['reason'])

    def test_exactly_representable_large_intermediate_and_floating_values(self):
        operands = {'x': Quantity(2.**53, {})}
        self.assertEqual(expression_value('x*2-x', operands).value, 2**53)
        self.assertAlmostEqual(expression_value('x/3', {'x': Quantity(1., {})}).value, 1/3)
        self.assertEqual(expression_value('x*2', {'x': Quantity(1e100, {})}).value, 2e100)

    def test_scaled_source_integer_cannot_round_before_expression_evaluation(self):
        q = self.bundle()
        path = self.root/'values.json'
        write_json(path, {'x': 3002399751580331})
        q['artifacts']['a']['sha256'] = sha256(path)
        q['units'] = {'triple': {'dimensions': {}, 'scale': 3}}
        q['claims'][0].update(expression='x-9007199254740992', value=0, unit='1',
                              operands={'x': {'artifact': 'a', 'locator': {'type': 'json_pointer', 'pointer': '/x'},
                                              'unit': 'triple', 'unit_basis': 'Three units per count'}},
                              tolerance={'absolute': 0, 'relative': 0})
        check = verify(q, self.root)['claims'][0]
        self.assertEqual(check['status'], 'failed')
        self.assertIn('integer intermediate', check['reason'])
    def test_unresolved_placeholders_rejected(self):
        for target in ['statement','unit_basis']:
            q=self.bundle()
            if target=='statement':q['claims'][0]['statement']='REPLACE_NUMERICAL_STATEMENT'
            else:q['claims'][0]['operands']['amount']['unit_basis']='REPLACE_MEASUREMENT_CONTRACT'
            self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_table_rows_remain_vector_even_for_one_row(self):
        q=self.bundle();path=self.root/'counts.xlsx';wb=openpyxl.Workbook();ws=wb.active;ws.title='Measures'
        ws.append(['payload','other']);ws.append([400,999]);wb.save(path)
        q['artifacts']['t']={'path':'counts.xlsx','sha256':sha256(path)}
        q['claims'][0]['operands']['amount']={'artifact':'t','locator':{'type':'table_rows','sheet':'Measures','header_row':1,'rows':[2],'field':'payload'},'unit':'byte','unit_basis':'Explicit payload column'}
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'passed')
        q['claims'][0]['operands']['amount']['locator']['field']='wrong'
        self.assertEqual(verify(q,self.root)['claims'][0]['status'],'failed')
    def test_manual_numeric_check_is_never_automatic_pass(self):
        q=self.bundle();q['claims'][0].update(verification='manual',reason='Requires inspection of a plotted annotation')
        r=verify(q,self.root);self.assertFalse(r['all_arithmetic_checked']);self.assertEqual(r['claims'][0]['status'],'not_checked')
    def test_source_mutation_during_verification_fails(self):
        import verify_claims
        q=self.bundle();original=verify_claims.select
        def changing(path,locator,cache):
            result=original(path,locator,cache)
            if locator.get('pointer')=='/duration':write_json(path,{'amount':[1],'duration':.2,'unit':'byte'})
            return result
        with patch.object(verify_claims,'select',side_effect=changing):r=verify(q,self.root)
        self.assertEqual(r['claims'][0]['status'],'failed')
    def test_report_without_figures_and_chinese_labels(self):
        q=self.ledger();p=self.root/'diagnosis.md';render(q,self.root,p)
        s=p.read_text(encoding='utf-8');self.assertIn('完成度与回答程度',s);self.assertIn('数值主张核验',s)
        self.assertNotIn('![',s)

    def test_v3_strong_claim_requires_a_specific_executed_result(self):
        q = self.ledger()
        path = self.root/'result.json'
        evidence = {'path': path.name, 'supports': 'Scoped synthetic result'}
        finding = {**q['phenomena'][0], 'id': 'F', 'status': 'validated_mechanism',
                   'claim_type': 'intervention_effect', 'explains': ['P1'], 'priority': 1,
                   'priority_reason': 'Synthetic case', 'mechanism': 'Synthetic design',
                   'support': 'Measured result', 'counterevidence': 'Scope limited',
                   'next_test': 'Replicate', 'prediction': 'A prespecified change',
                   'strongest_alternative': 'A competing explanation', 'evidence': [evidence],
                   'validation': {'result_path': path.name, 'design': 'Paired randomization',
                                  'independent_replication': 'Separate pairs', 'reviewer_assessment': 'Fixture reviewed',
                                  'identification_scope': 'Synthetic pairs'}}
        q['findings'] = [finding]
        request, data = paired_fixture()
        result = causal(request, data)
        for document, pointer, allowed in [
                ({'inputs': [], 'options': {}}, '', False),
                (12.5, '', True),
                ({'values': [12.5]}, '/values/0', True),
                ({'analyses': [{'estimate': 12.5}], 'execution_summary': {'completed': 1}},
                 '/analyses/0/estimate', True),
                (result, '/configuration', False),
                (result, '/analyses/0/result/design', False),
                (result, '/analyses/0/result/inference/assumptions_verified_by_software', False),
                (result, '/analyses/0/result/pairs/0/unit_id', False),
                (result, '/analyses/0/result/summary/uncertainty', False),
                (result, '/analyses/0/result/pairs/0', True),
                (result, '/analyses/0/result/pairs/0/difference', True),
                (result, '/analyses/0/result/p_value', True)]:
            with self.subTest(pointer=pointer, allowed=allowed):
                write_json(path, document)
                evidence.update(sha256=sha256(path), locator={'type': 'json_pointer', 'pointer': pointer})
                if allowed:
                    validate_evidence(q, self.root)
                else:
                    with self.assertRaisesRegex(ValueError, 'specific located result'):
                        validate_evidence(q, self.root)
        request['analyses'][0]['design'] = {'type': 'observational_paired'}
        write_json(path, causal(request, data))
        evidence.update(sha256=sha256(path), locator={'type': 'json_pointer', 'pointer': '/analyses/0/result/summary'})
        with self.assertRaisesRegex(ValueError, 'specific located result'):
            validate_evidence(q, self.root)
        config = self.root/'config.json'
        finding['validation']['result_path'] = config.name
        evidence.update(path=config.name, sha256=sha256(config),
                        locator={'type': 'json_pointer', 'pointer': '/description'})
        with self.assertRaisesRegex(ValueError, 'specific located result'):
            validate_evidence(q, self.root)
    def test_json_export_is_independent_of_presentation_language(self):
        q=self.ledger();q['language']='other-language';p=self.root/'diagnosis.json'
        render(q,self.root,p,output_format='json');r=read_json(p)
        self.assertEqual(r['ledger']['language'],'other-language');self.assertEqual(r['numerical_checks']['claims'][0]['status'],'passed')
    def test_unknown_markdown_language_needs_labels(self):
        q=self.ledger();q['language']='other-language'
        with self.assertRaises(ValueError):render(q,self.root,self.root/'diagnosis.md')
    def test_unfinished_check_cannot_mark_delivery_passed(self):
        q=self.ledger();q['assessment']['delivery_quality']['status']='passed'
        q['assessment']['delivery_quality']['checks'][0]['status']='not_checked'
        with self.assertRaises(ValueError):validate_evidence(q,self.root)
    def test_wrong_claim_blocks_report(self):
        q=self.ledger();q['numeric_claims']['claims'][0]['value']=32
        with self.assertRaises(ValueError):render(q,self.root,self.root/'wrong.md')
    def test_output_cannot_replace_numeric_source(self):
        q=self.ledger();before=sha256(self.root/'values.json')
        with self.assertRaises(ValueError):render(q,self.root,self.root/'values.json',output_format='json')
        self.assertEqual(sha256(self.root/'values.json'),before)
    def test_unlinked_claim_is_rejected(self):
        q=self.ledger();q['phenomena'][0]['claim_ids']=[]
        with self.assertRaises(ValueError):validate_evidence(q,self.root)
    def test_semantic_review_is_not_implied_by_arithmetic_pass(self):
        q=self.ledger();q['claim_review']['status']='not_checked';q['assessment']['delivery_quality']['status']='passed'
        with self.assertRaises(ValueError):validate_evidence(q,self.root)
    def test_snapshot_checks_hash_of_exact_parsed_bytes(self):
        p=self.root/'snapshot.json';write_json(p,{'value':2});expected=sha256(p)
        data,digest=snapshot_json(p,expected);write_json(p,{'value':100})
        self.assertEqual(data['value'],2);self.assertEqual(digest,expected)
        with self.assertRaises(ValueError):snapshot_json(p,expected)
    def test_analysis_does_not_claim_changed_input_is_unchanged(self):
        q,d=causal_fixture();source=self.root/'data.json';write_json(source,d)
        q['data']={'path':'data.json','sha256':sha256(source)};request=self.root/'request.json';write_json(request,q)
        output=self.root/'output.json'
        def changing(config,data):
            result=causal(config,data);write_json(source,{'records':[]});return result
        with patch.object(sys,'argv',['causal_analysis.py','--request',str(request),'--output',str(output)]):
            with self.assertRaises(ValueError):run_analysis_cli(changing,__file__,'test')
        self.assertFalse(output.exists())


if __name__=='__main__':
    unittest.main(verbosity=2)

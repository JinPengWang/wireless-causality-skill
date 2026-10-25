"""Regression cases for measurement semantics and evidence boundaries; synthetic only."""
import copy
import tempfile
import unittest
from pathlib import Path
import openpyxl
from common import sha256,table_rows
from build_windows import build
from wifi_frames import decode_compressed_ba,observed_ba_status,observed_retry_chains,effective_rate_proxy
from compare_runs import summarize,paired_compare
from detect_events import detect
from write_report import validate_evidence


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.test_base=Path(__file__).resolve().parents[1]/'logs'/'tool_tests'
        self.test_base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=self.test_base,prefix='case_');self.root=Path(self.tmp.name)
    def tearDown(self):
        if self.root.resolve().parent != self.test_base.resolve():raise RuntimeError('Unexpected test cleanup path')
        self.tmp.cleanup()
    def workbook(self,headers,rows,name='arbitrary.xlsx'):
        path=self.root/name;wb=openpyxl.Workbook();ws=wb.active;ws.title='Telemetry';ws.append(headers)
        for row in rows:ws.append(row)
        wb.save(path);return path
    def request(self,rows,kind='interval_amount',width=1):
        path=self.workbook(['left','right','v','bad','all'],rows)
        return {'schema_version':1,'window_s':width,'sources':[{'path':str(path),'sheet':'Telemetry',
          'metadata':{'run_id':'r','entity':'x','direction':'forward','condition':'c','pair_id':'p'},
          'time':{'start':'left','end':'right','scale':1,'origin':0,'split_policy':'reject'},
          'metrics':[{'name':'m','unit':'unit/s','kind':kind,'column':'v','numerator':'bad','denominator':'all','scale':1,'definition':'synthetic explicit measurement'}]}]}
    def test_interval_rate_uses_elapsed_time(self):
        q=self.request([[0,.5,10,0,1],[.5,1,30,0,1]])
        self.assertEqual(build(q)['windows'][0]['value'],40)
    def test_missing_metric_not_zero(self):
        q=self.request([[0,1,None,0,1]])
        self.assertIsNone(build(q)['windows'][0]['value'])
    def test_count_ratio_not_mean_of_percentages(self):
        q=self.request([[0,.5,0,1,1],[.5,1,0,0,9]],'ratio')
        self.assertAlmostEqual(build(q)['windows'][0]['value'],.1)
    def test_run_ratio_pools_counts_across_windows(self):
        q=self.request([[0,1,0,1,1],[1,2,0,0,9]],'ratio')
        self.assertAlmostEqual(summarize(build(q)['windows'])[0]['mean'],.1)
    def test_zero_denominator_is_missing(self):
        q=self.request([[0,1,0,0,0]],'ratio');self.assertIsNone(build(q)['windows'][0]['value'])
    def test_invalid_ratio_rejected(self):
        with self.assertRaises(ValueError):build(self.request([[0,1,0,3,2]],'ratio'))
    def test_gap_preserved(self):
        rows=build(self.request([[0,1,2,0,1],[2,3,2,0,1]]))['windows']
        self.assertEqual(len(rows),3);self.assertIsNone(rows[1]['value']);self.assertEqual(rows[1]['coverage'],0)
    def test_overlapping_intervals_rejected(self):
        with self.assertRaises(ValueError):build(self.request([[0,1,2,0,1],[.5,1.5,3,0,1]]))
    def test_unsorted_intervals_rejected(self):
        with self.assertRaises(ValueError):build(self.request([[1,2,2,0,1],[0,1,3,0,1]]))
    def test_split_requires_explicit_policy(self):
        with self.assertRaises(ValueError):build(self.request([[0,2,8,0,1]]))
    def test_uniform_allocation_conserves_amount(self):
        q=self.request([[0,2,8,0,1]]);q['sources'][0]['time']['split_policy']='uniform'
        rows=build(q)['windows'];self.assertEqual(sum(r['value']*(r['end_s']-r['start_s']) for r in rows),8)
    def test_millisecond_clock_and_different_origin(self):
        q=self.request([[19000,19500,3,0,1],[19500,20000,4,0,1]])
        q['sources'][0]['time'].update(scale=.001,origin=19)
        self.assertEqual(build(q)['windows'][0]['value'],7)
    def test_headers_can_be_renamed(self):
        q=self.request([[0,1,8,0,1]]);p=self.workbook(['alpha','omega','octets'],[[0,1,8]],'not_a_capture_name.xlsx')
        q['sources'][0]['path']=str(p);q['sources'][0]['time'].update(start='alpha',end='omega')
        q['sources'][0]['metrics'][0]['column']='octets'
        self.assertEqual(build(q)['windows'][0]['value'],8)
    def test_typo_not_silent_missing(self):
        q=self.request([[0,1,8,0,1]]);q['sources'][0]['metrics'][0]['column']='typo'
        with self.assertRaises(ValueError):build(q)
    def test_unknown_request_key_rejected(self):
        q=self.request([[0,1,8,0,1]]);q['window']=1
        with self.assertRaises(ValueError):build(q)
    def test_duplicate_headers_rejected(self):
        p=self.workbook(['a','a'],[[1,2]])
        with self.assertRaises(ValueError):list(table_rows(p))
    def test_multiple_sources_cannot_double_count(self):
        q=self.request([[0,1,8,0,1]]);q['sources'].append(copy.deepcopy(q['sources'][0]))
        with self.assertRaises(ValueError):build(q)
    def event_request(self,complete):
        q=self.request([[.1,.1,1,0,1],[2.1,2.1,0,0,1]],'event_fraction')
        q['sources'][0]['time'].pop('end');q['sources'][0]['time']['observation_interval']=[0,3]
        q['sources'][0]['capture_complete']=complete;return q
    def test_empty_partial_capture_window_is_unknown(self):
        rows=build(self.event_request(False))['windows'];self.assertEqual(rows[1]['coverage'],0);self.assertIsNone(rows[1]['value'])
    def test_binary_fraction_rejects_retry_counts(self):
        q=self.event_request(True);q['sources'][0]['metrics'][0]['column']='all'
        p=self.workbook(['left','all'],[[.1,4]],'counts.xlsx');q['sources'][0]['path']=str(p)
        with self.assertRaises(ValueError):build(q)
    def test_empty_complete_capture_count_zero(self):
        q=self.event_request(True);q['sources'][0]['metrics'][0]['kind']='event_count'
        self.assertEqual(build(q)['windows'][1]['value'],0)
    def test_value_map_is_explicit(self):
        q=self.event_request(True);p=self.workbook(['left','flag'],[[.1,'retry'],[.2,'first']], 'flags.xlsx');q['sources'][0]['path']=str(p)
        q['sources'][0]['metrics'][0].update(column='flag',value_map={'retry':1,'first':0})
        self.assertEqual(build(q)['windows'][0]['value'],.5)
    def test_ba_wire_order_and_wrap(self):
        bits=decode_compressed_ba(4095,'0300000000000000',64)
        self.assertTrue(bits[4095]);self.assertTrue(bits[0]);self.assertFalse(bits[1])
    def test_ba_only_supplied_observed_sequences(self):
        statuses=observed_ba_status(10,'0100000000000000',64,[10,11,100])
        self.assertEqual(len(statuses),3);self.assertEqual(statuses['100'],'outside_bitmap')
    def test_ba_wrong_length_rejected(self):
        with self.assertRaises(ValueError):decode_compressed_ba(0,'01',64)
    def test_ba_unsupported_variant_rejected(self):
        with self.assertRaises(ValueError):decode_compressed_ba(0,'01',8)
    def frames(self):
        return [{'capture_id':'cap','transmitter':'tx','receiver':'rx','tid':0,'seq':9,'fragment':0,'time_s':i*.01,'retry':int(i>0),'source_row':i+2} for i in range(3)]
    def test_retry_chains_censored_not_limit(self):
        result=observed_retry_chains(self.frames(),.1)['chains'][0]
        self.assertEqual(result['attempts_observed'],3);self.assertTrue(result['right_censored'])
    def test_retry_queues_not_merged(self):
        f=self.frames();f[1]['tid']=1
        self.assertEqual(len(observed_retry_chains(f,.1)['chains']),2)
    def test_retry_missing_tid_blocked(self):
        f=self.frames();f[0]['tid']=None
        with self.assertRaises(ValueError):observed_retry_chains(f,.1)
    def test_retry_fractional_sequence_rejected(self):
        f=self.frames();f[0]['seq']=9.5
        with self.assertRaises(ValueError):observed_retry_chains(f,.1)
    def test_retry_unknown_address_rejected(self):
        f=self.frames();f[0]['transmitter']='unknown'
        with self.assertRaises(ValueError):observed_retry_chains(f,.1)
    def test_retry_sequence_reuse_splits(self):
        f=self.frames();f[2]['retry']=0
        self.assertEqual(len(observed_retry_chains(f,.1)['chains']),2)
    def test_proxy_unknown_per_not_zero(self):
        self.assertIsNone(effective_rate_proxy(100,None,10));self.assertIsNone(effective_rate_proxy(100,0,0))
        self.assertEqual(effective_rate_proxy(100,2,10),80)
    def windows(self,values):
        return [{'run_id':'r','entity':'A','direction':'forward','condition':'c','pair_id':'p','metric':'m','unit':'u',
                 'start_s':i,'end_s':i+1,'value':v,'coverage':1,'source_rows':[i+2],
                 'kind':'interval_mean','definition':'Synthetic interval outcome averaged over observed time'} for i,v in enumerate(values)]
    def test_run_weighting_is_duration_weighted(self):
        w=self.windows([0,10]);w[1]['end_s']=4
        self.assertEqual(summarize(w)[0]['mean'],7.5)
    def test_comparison_separates_directions(self):
        a=summarize(self.windows([10]))[0];b={**a,'entity':'B','run_id':'b','direction':'reverse','mean':3}
        out=paired_compare([a,b],'A')
        self.assertTrue(all(r['status']=='blocked_no_common_support' for r in out))
    def test_unknown_pair_does_not_become_replicate(self):
        a=summarize(self.windows([10]))[0];a['pair_id']='unknown'
        self.assertEqual(paired_compare([a],'A')[0]['status'],'blocked_no_eligible_pairs')
    def test_small_cohort_no_false_precision(self):
        a=summarize(self.windows([10]))[0];b={**a,'entity':'B','run_id':'b','mean':8}
        r=paired_compare([a,b],'A')[0];self.assertEqual(r['mean_target_minus_reference'],-2);self.assertIsNone(r['ci95'])
    def test_onset_and_recovery_censoring(self):
        e=detect(self.windows([1,1,10]),5,'below',1,.8,2)[0]
        self.assertFalse(e['onset_observed']);self.assertTrue(e['recovery_censored'])
    def test_gap_does_not_join_events(self):
        w=self.windows([1,None,1]);w[1]['coverage']=0
        self.assertEqual(len(detect(w,5,'below',1,.8,1)),2)
    def test_observed_recovery(self):
        e=detect(self.windows([10,1,10,10]),5,'below',1,.8,2)[0]
        self.assertTrue(e['onset_observed']);self.assertEqual(e['recovery_start_s'],2)
    def test_evidence_hash_change_rejected(self):
        path=self.root/'evidence.json';path.write_text('{}');fig=self.root/'fig.svg';fig.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>')
        item={'id':'p','statement':'x','status':'observed','calculation':'x','evidence':[{'path':'evidence.json','sha256':sha256(path),'locator':{'type':'json_pointer','pointer':''}}],
              'figures':[{'path':'fig.svg','sha256':sha256(fig),'caption':'x'}],'limitations':'x'}
        report={'schema_version':2,'analysis_status':'completed','question':'x','scope':'x','measurement_contract':'x','phenomena':[item],'findings':[],'limitations':'x','reproduce':'x'}
        validate_evidence(report,self.root);path.write_text('{"changed":true}')
        with self.assertRaises(ValueError):validate_evidence(report,self.root)

if __name__=='__main__':unittest.main(verbosity=2)

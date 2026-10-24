"""Regression tests for diagnostic reasoning, support selection, and transfer."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from test_core import sle_frame
from data_io import _derive,read_json,load_mapped_csv,aggregate_blocks
from request_contract import resolve_request,scope_data,validate_adapter,measurement_profiles
from case_engine import detect_target_events,build_casebook,diff_casebooks,window_summary
from comparison import compare_cohort

SKILL=Path(__file__).resolve().parents[1]
ADAPTER=read_json(SKILL/"assets/sle_adapter.json")
CATALOG=read_json(SKILL/"assets/hypothesis_catalog.json")

def episode(no_tx=False):
    d=sle_frame(1501)
    select=d.index.to_series().between(1000,1030)
    d.loc[select,"total_tx_size"]=125
    d.loc[select,"tx_ack"]=1
    d.loc[select,"interf_avg"]=-90
    if no_tx:d.loc[select,["tx_total","tx_ack","total_tx_size"]]=0
    d=_derive(d,ADAPTER)
    return d

def contract(**kwargs):
    r={"question":"为什么这个窗口掉坑？","case_budget":1,"scope":{}}
    r.update(kwargs)
    return resolve_request(r,ADAPTER)

def make_case(d,c=None,screen=None):
    c=c or contract()
    ev,a=detect_target_events(d,c)
    return build_casebook(a,ev,pd.DataFrame() if screen is None else screen,c,ADAPTER,CATALOG)

class InvestigationTests(unittest.TestCase):
    def test_unknown_request_field_fails_instead_of_ignored(self):
        with self.assertRaises(ValueError):contract(candidate_casues=["rssi_valid"])

    def test_request_seed_and_candidates_are_executable(self):
        c=contract(seed=7,candidate_causes=["interf_avg"])
        self.assertEqual(c["seed"],7);self.assertEqual(c["candidate_causes"],["interf_avg"])

    def test_outcome_and_identity_not_called_cause(self):
        for field in ["throughput_kbps","tx_flushed","hdl","ack_ratio"]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):contract(candidate_causes=[field])

    def test_legacy_template_remains_explicitly_supported(self):
        c=resolve_request({"task":"throughput_dip","reference":"past_10_seconds_within_stream",
            "min_event_seconds":.4,"dip_fraction":.7},ADAPTER)
        self.assertEqual(c["task"],"diagnose");self.assertEqual(c["detector"]["drop_fraction"],.7)

    def test_task_conflict_rejected(self):
        with self.assertRaises(ValueError):resolve_request({"task":"diagnose"},ADAPTER,task="compare")

    def test_scope_does_not_include_other_links(self):
        d=episode();other=d.copy();other["hdl"]=6;other["stream_id"]="other"
        scoped=scope_data(pd.concat([d,other]),contract(scope={"hdl":[5]}))
        self.assertEqual(set(scoped.hdl),{5})

    def test_unavailable_scope_is_not_silently_empty(self):
        with self.assertRaises(ValueError):scope_data(episode(),contract(scope={"hdl":[99]}))

    def test_nearest_past_reference_and_real_signal_competition(self):
        book=make_case(episode());c=book["cases"][0];ref=c["reference"]
        self.assertEqual(ref["status"],"selected")
        self.assertLessEqual(ref["end_s"],c["start_s"]-2+1e-8)
        self.assertAlmostEqual(c["event"]["metrics"]["throughput_kbps"]["value"],10)
        self.assertAlmostEqual(ref["metrics"]["throughput_kbps"]["value"],100)
        claims={x["hypothesis_id"]:x for x in c["hypotheses"]}
        self.assertEqual(claims["external_interference"]["status"],"supported_candidate")
        self.assertEqual(claims["path_loss"]["status"],"weakened_in_this_window")
        self.assertTrue(all(not x["root_cause_confirmed"] for x in c["hypotheses"]))

    def test_reference_never_borrows_another_stream(self):
        d=episode();d.loc[d.index<1000,"pwrlev"]=7
        other=episode();other["stream_id"]="other";other["hdl"]=6
        c=contract(focus={"stream_id":d.stream_id.iloc[0],"start_s":99.9,"end_s":103.0})
        book=make_case(pd.concat([d,other],ignore_index=True),c)
        self.assertEqual(book["cases"][0]["reference"]["status"],"unavailable")

    def test_future_feature_strength_forces_direction_warning(self):
        d=episode()
        rows=[]
        for lag in [-1,1]:
            rows.append({"stream_id":d.stream_id.iloc[0],"piece":0,"feature":"interf_avg","outcome":"throughput_kbps",
              "lag_s":lag,"run":1,"spearman_rho":-.9,"detrended_rho":-.9,"q_shift_exploratory":.01})
        c=make_case(d,screen=pd.DataFrame(rows))["cases"][0]
        h=next(x for x in c["hypotheses"] if x["hypothesis_id"]=="external_interference")
        self.assertTrue(any("时间方向未分辨" in x for x in h["limitations"]))

    def test_unmeasured_candidate_is_not_excluded(self):
        d=episode().drop(columns=["interf_avg"])
        c=make_case(d)["cases"][0]
        h=next(x for x in c["hypotheses"] if x["hypothesis_id"]=="external_interference")
        self.assertEqual(h["status"],"untestable")
        self.assertEqual(h["counterevidence"],[])

    def test_no_tx_does_not_prove_radio_failure_or_idle(self):
        c=make_case(episode(no_tx=True))["cases"][0]
        h=next(x for x in c["hypotheses"] if x["hypothesis_id"]=="demand_change")
        self.assertEqual(h["status"],"unresolved");self.assertEqual(h["review_priority"],"investigate")
        self.assertIsNone(c["causal_effect"])

    def test_manual_focus_cannot_cross_dropout(self):
        d=episode();d.loc[d.index>=1010,"piece"]=1
        c=contract(focus={"stream_id":d.stream_id.iloc[0],"start_s":99,"end_s":104})
        with self.assertRaises(ValueError):make_case(d,c)

    def test_focused_event_id_is_resolved_not_ignored(self):
        d=episode();base=contract();events,_=detect_target_events(d,base)
        chosen=events.event_id.iloc[0]
        c=contract(focus={"event_id":chosen})
        self.assertEqual(make_case(d,c)["cases"][0]["case_id"],chosen)

    def test_raw_row_membership_survives_input_row_shuffle(self):
        d=episode();rng=np.random.default_rng(5);d["source_row"]=rng.permutation(d.source_row.to_numpy())
        c=make_case(d)["cases"][0]
        refs=c["event"]["source_refs"][0]["rows"]
        self.assertEqual(len(refs),31)
        self.assertAlmostEqual(c["event"]["metrics"]["throughput_kbps"]["value"],10)

    def test_reference_rejects_configuration_change(self):
        d=episode();d.loc[d.time_s.between(100.5,102),"pwrlev"]=7
        c=make_case(d)["cases"][0]
        self.assertEqual(c["reference"]["reason"],"event_settings_vary")

    def test_absolute_sla_detects_persistently_slow_signal(self):
        d=episode();d["throughput_kbps"]=10
        c=contract(detector={"mode":"absolute","absolute_threshold":50})
        events,_=detect_target_events(d,c)
        self.assertEqual(len(events),1)
        self.assertGreater(events.observed_duration_s.iloc[0],100)

    def test_removed_case_in_revision_is_not_refutation(self):
        previous=make_case(episode());current={**previous,"cases":[],"case_count":0}
        diff=diff_casebooks(previous,current)
        self.assertEqual(diff["changes"][0]["change"],"not_in_current_scope_not_refuted")

    def test_constant_printed_value_not_sensor_refresh_claim(self):
        p=measurement_profiles(episode(),["pwrlev"]).iloc[0]
        self.assertEqual(p.value_changes,0);self.assertIn("not_proof",p.interpretation)

    def test_count_metric_is_normalized_by_time_not_report_count(self):
        d=episode().iloc[:5].copy();d["abnormal_cnt"]=2;d["dt"]=.2;d["valid_rate_interval"]=True
        self.assertAlmostEqual(window_summary(d,ADAPTER)["metrics"]["abnormal_cnt"]["value"],10)

    def test_protocol_transfer_and_latency_without_throughput(self):
        a=deepcopy(read_json(SKILL/"assets/wifi_adapter.json"))
        a["protocol"]="custom_radio";a["default_outcome"]="latency_ms"
        a["metrics"]={"latency_ms":{"source":"delay","kind":"gauge","unit":"ms"}}
        validate_adapter(a)
        with tempfile.TemporaryDirectory(prefix="wireless_v2_",dir=Path.cwd()) as temp:
            assert Path(temp).resolve().is_relative_to(Path.cwd().resolve())
            p=Path(temp)/"trace.csv"
            d=pd.DataFrame({"timestamp":pd.date_range("2026-01-01",periods=101,freq="100ms"),
                "device_id":"A","session_id":"s","scenario":"lab","link_id":"l","delay":50})
            d.to_csv(p,index=False)
            loaded,*_=load_mapped_csv(p,a)
            c=resolve_request({"primary_outcome":"latency_ms","detector":{"mode":"absolute","absolute_threshold":20}},a)
            events,_=detect_target_events(scope_data(loaded,c),c)
            self.assertEqual(len(events),1)

    def test_multi_device_requires_explicit_reference(self):
        d=episode();d["device_id"]="A";other=d.copy();other["device_id"]="B";third=d.copy();third["device_id"]="C"
        status,_=compare_cohort(pd.concat([d,other,third]),contract(),ADAPTER)
        self.assertEqual(status["status"],"blocked")

    def test_cohort_common_support_and_simpson_guard(self):
        rows=[]
        for pair in range(10):
            for scenario,baseline in [("low",100),("high",1000)]:
                for dev,offset in [("A",0),("B",-10),("C",20)]:
                    if dev=="C" and pair==0:continue
                    n=9 if (dev=="B" and scenario=="high") or (dev=="A" and scenario=="low") else 1
                    for i in range(n):
                        rows.append({"dataset":"test","condition":scenario,"pair_id":str(pair),"device_id":dev,
                          "hdl":"w","stream_id":dev+scenario+str(pair),"source_file":"synthetic","source_row":len(rows)+2,
                          "valid_rate_interval":True,"dt":.1,"throughput_kbps":baseline+offset})
        d=pd.DataFrame(rows)
        c=contract(task="compare",comparison={"reference_device":"A","target_devices":["B","C"],
                  "match_fields":["condition","pair_id"]})
        status,pairs=compare_cohort(d,c,ADAPTER)
        self.assertGreater(d[d.device_id.eq("B")].throughput_kbps.mean(),d[d.device_id.eq("A")].throughput_kbps.mean())
        b=next(x for x in status["comparisons"] if x["target_device"]=="B")
        self.assertAlmostEqual(b["contrasts"][0]["mean_target_minus_reference"],-10)
        other=next(x for x in status["comparisons"] if x["target_device"]=="C")
        self.assertAlmostEqual(other["reference_common_fraction"],.9)
        self.assertEqual(len(pairs[pairs.target_device.eq("C")]),18)

    def test_single_device_is_blocked(self):
        d=episode();d["device_id"]="A"
        result,_=compare_cohort(d,contract(task="compare"),ADAPTER)
        self.assertEqual(result["status"],"blocked")

    def test_kind_unit_conflict_rejected(self):
        a=deepcopy(read_json(SKILL/"assets/wifi_adapter.json"))
        a["metrics"]["throughput_kbps"]["unit"]="count"
        with self.assertRaises(ValueError):validate_adapter(a)

    def test_duplicate_matching_fields_rejected(self):
        with self.assertRaises(ValueError):contract(comparison={"match_fields":["pair_id","pair_id"]})

    def test_no_common_conditions_not_a_successful_comparison(self):
        d=episode();d["device_id"]="A";d["pair_id"]="p1"
        other=d.copy();other["device_id"]="B";other["pair_id"]="p2"
        c=contract(task="compare",comparison={"match_fields":["pair_id"]})
        result,_=compare_cohort(pd.concat([d,other]),c,ADAPTER)
        self.assertEqual(result["status"],"blocked_no_common_measured_support")
        self.assertEqual(len(result["comparisons"][0]["unmatched_conditions"]),2)

    def test_no_tx_next_action_checks_application_before_root_claim(self):
        c=make_case(episode(no_tx=True))["cases"][0]
        self.assertIsNone(c["decision"]["confirmed_root_cause"])
        self.assertIn("应用入队",c["decision"]["next_actions"][0]["action"])

    def test_adaptive_event_keeps_unmatched_trajectory_and_phases(self):
        d=episode();d.loc[d.time_s.between(100.5,102),"bitrate"]=96
        c=make_case(d)["cases"][0]
        self.assertEqual(c["reference"]["status"],"unavailable")
        self.assertGreater(len(c["configuration_phases"]),1)
        self.assertEqual(c["prelude"]["status"],"available_unmatched_process_context")
        self.assertEqual(c["trajectory_deltas"]["interf_avg"]["status"],"up")
        h=next(x for x in c["hypotheses"] if x["hypothesis_id"]=="external_interference")
        self.assertEqual(h["status"],"unresolved")
        self.assertEqual(c["decision"]["next_actions"][0]["type"],"phase_review")

    def test_roundoff_must_not_manufacture_ranked_variation(self):
        from diagnostics import lag_screen
        b=pd.DataFrame({"stream_id":"s","piece":0,"block":np.arange(100),"eligible":True,
            "x":160+np.arange(100)%3*np.spacing(160.),"y":np.arange(100),"dataset":"s","condition":"lab","segment":"s","hdl":5})
        self.assertEqual(len(lag_screen(b,["x"],["y"])),0)

    def test_manual_focus_inside_existing_problem_flags_clipped_onset(self):
        d=episode()
        c=make_case(d,contract(focus={"stream_id":d.stream_id.iloc[0],"start_s":101,"end_s":103}))["cases"][0]
        self.assertTrue(c["onset_context"]["focus_may_clip_existing_symptom"])
        self.assertEqual(c["decision"]["next_actions"][0]["type"],"onset_review")

    def test_missing_reset_detection_is_not_zero_resets(self):
        c=make_case(episode())["cases"][0]
        self.assertIsNone(c["event"]["counter_reset_reports"])
        h=next(x for x in c["hypotheses"] if x["hypothesis_id"]=="collection_artifact")
        self.assertEqual(h["status"],"unresolved")

if __name__=="__main__":unittest.main(verbosity=2)

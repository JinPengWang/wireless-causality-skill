"""Executable regression tests for failure modes with scientific consequences.
All generated data is explicitly synthetic and does not validate real causal claims.
"""
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from data_io import _derive,read_json,load_mapped_csv,aggregate_blocks
from diagnostics import detect_events,compare_devices,bh_adjust,lag_screen,summarize
from causal import causal_gate,estimate_switchback,REQUIRED_ATTESTATIONS
SKILL=Path(__file__).resolve().parents[1]

def sle_frame(n=100):
    t=np.arange(n)*.1
    return pd.DataFrame({"dataset":"synthetic","condition":"lab","segment":"s","hdl":5,
      "device_id":pd.NA,"stream_id":"synthetic|lab|s|5","session_id":"s",
      "time":[f"00:{x:04.1f}" for x in t],"dt":np.r_[np.nan,np.repeat(.1,n-1)],
      "total_tx_size":1250.0,"tx_flushed":0.0,"tx_ack":9.0,"tx_total":10.0,
      "rssi_avg":-60.0,"cnt_diff_total":10.0,"cnt_total_nb":5.0,
      "source_file":"synthetic.csv","source_row":np.arange(n)+2,
      "interf_avg":-100.0,"bitrate":160.0,"pwrlev":6.0})

def simulated_switchback(effect=-30.0,sessions=10):
    rows=[];blocks=[];rng=np.random.default_rng(5)
    for s in range(sessions):
        sid=f"synthetic_{s}";order=[0,1] if rng.integers(2) else [1,0]
        for b,tr in enumerate(order):
            blocks.append({"session_id":sid,"block_id":f"b{b}","pair_id":"p1",
                "start_s":b*20.0,"end_s":(b+1)*20.0,"treatment":tr,"assignment_source":"synthetic_randomization_log"})
        for link in ["left","right"]:
            for t in np.arange(.1,40.01,.1):
                tr=order[0] if t<=20 else order[1]
                rows.append({"session_id":sid,"stream_id":sid+"_"+link,"time_s":t,"dt":.1,
                    "valid_rate_interval":True,"throughput_kbps":100+s+effect*tr})
    design={x:True for x in REQUIRED_ATTESTATIONS}
    design.update({"design":"randomized_paired_switchback","estimand":"synthetic ATE",
      "treatment_definition":"synthetic external switch","outcome":"throughput_kbps",
      "randomization_protocol":"synthetic paired random order, seed5","population":"synthetic sessions",
      "washout_s":2.0,"min_coverage":.8})
    return pd.DataFrame(rows),pd.DataFrame(blocks),design

class CoreTests(unittest.TestCase):
    def test_real_interval_units_and_flags(self):
        d=sle_frame(4);d.loc[1,"dt"]=.2;d.loc[2,"dt"]=0;d.loc[3,"tx_flushed"]=7
        q=_derive(d,read_json(SKILL/"assets/sle_adapter.json"))
        self.assertAlmostEqual(q.throughput_kbps.iloc[1],50)
        self.assertTrue(np.isnan(q.throughput_kbps.iloc[2]))
        self.assertEqual(q.tx_flushed.iloc[3],7)
        self.assertEqual(q.stall_flag.iloc[3],1)
        self.assertAlmostEqual(q.delay_proxy_ms.iloc[1],40)

    def test_zero_ack_denominator_and_rssi_sentinel(self):
        d=sle_frame(3);d.loc[1,["tx_total","tx_ack","rssi_avg"]]=0
        q=_derive(d,read_json(SKILL/"assets/sle_adapter.json"))
        self.assertTrue(np.isnan(q.ack_ratio.iloc[1]))
        self.assertTrue(np.isnan(q.rssi_valid.iloc[1]))
        self.assertEqual(q.rssi_avg.iloc[1],0)

    def test_short_time_uses_dt_not_date_guess(self):
        d=sle_frame(3);d["time"]=["59:59.9","00:00.0","00:00.1"]
        q=_derive(d,read_json(SKILL/"assets/sle_adapter.json"))
        np.testing.assert_allclose(q.time_s,[0,.1,.2])
        self.assertTrue(q.time_method.eq("relative_reconstructed_from_dt").all())

    def test_gap_never_becomes_zero_rate_dip(self):
        d=sle_frame(100);d.loc[60,"dt"]=37.145;d.loc[60:,"total_tx_size"]=0
        q=_derive(d,read_json(SKILL/"assets/sle_adapter.json"))
        self.assertTrue(np.isnan(q.throughput_kbps.iloc[60]))
        events,_=detect_events(q)
        self.assertEqual(len(events[events.kind.eq("throughput_dip")]),0)

    def test_injected_drop_is_localized(self):
        d=sle_frame(150);d.loc[80:90,"total_tx_size"]=125
        q=_derive(d,read_json(SKILL/"assets/sle_adapter.json"))
        events,_=detect_events(q)
        dips=events[events.kind.eq("throughput_dip")]
        self.assertEqual(len(dips),1)
        self.assertAlmostEqual(dips.start_s.iloc[0],7.9,places=6)
        self.assertAlmostEqual(dips.observed_duration_s.iloc[0],1.1,places=6)

    def test_no_false_device_identity(self):
        q=_derive(sle_frame(),read_json(SKILL/"assets/sle_adapter.json"))
        status,pairs=compare_devices(q,{})
        self.assertEqual(status["status"],"blocked")
        self.assertEqual(len(pairs),0)

    def test_wifi_counter_reset_and_identity(self):
        adapter=read_json(SKILL/"assets/wifi_adapter.json")
        with tempfile.TemporaryDirectory(prefix="wireless_test_", dir=Path.cwd()) as temp:
            assert Path(temp).resolve().is_relative_to(Path.cwd().resolve())
            rows=[]
            for dev in ["A","B"]:
                for i,val in enumerate([0,1250,2500,10,1260]):
                    rows.append({"timestamp":"2026-01-01T00:00:00+00:00" if i==0 else f"2026-01-01T00:00:00.{i}+00:00","device_id":dev,
                      "session_id":"s1","scenario":"lab","link_id":"wlan0","app_rx_bytes_total":val})
            path=Path(temp)/"synthetic_wifi.csv";pd.DataFrame(rows).to_csv(path,index=False)
            d,*_=load_mapped_csv(path,adapter)
            self.assertEqual(d.stream_id.nunique(),2)
            self.assertEqual(int(d.counter_reset.sum()),2)
            self.assertTrue(d.loc[d.counter_reset,"throughput_kbps"].isna().all())
            self.assertTrue(np.allclose(d.throughput_kbps.dropna(),100))
            self.assertEqual(len(summarize(d)),2)

    def test_bh_family(self):
        np.testing.assert_allclose(bh_adjust([.01,.04,.03]),[.03,.04,.04])

    def test_constant_features_not_tested(self):
        b=pd.DataFrame({"stream_id":"s","piece":0,"block":np.arange(100),"eligible":True,
          "x":1.0,"y":np.arange(100),"dataset":"s","condition":"lab","segment":"s","hdl":5})
        self.assertEqual(len(lag_screen(b,["x"],["y"])),0)

    def test_causal_requires_independent_design(self):
        self.assertEqual(causal_gate()["status"],"not_identified")
        d,b,design=simulated_switchback()
        design["independent_treatment_log"]=False
        result,_=estimate_switchback(d,b,design)
        self.assertEqual(result["status"],"not_identified")
        self.assertIsNone(result["causal_effect"])

    def test_recovers_known_randomized_effect_and_clusters_links(self):
        d,b,design=simulated_switchback()
        result,_=estimate_switchback(d,b,design)
        self.assertAlmostEqual(result["estimate"],-30,places=6)
        self.assertEqual(result["n_independent_sessions_assumed"],10)
        self.assertLess(result["p_signflip"],.01)
        self.assertLessEqual(result["ci95"][0],-30+1e-6)
        self.assertGreaterEqual(result["ci95"][1],-30-1e-6)

    def test_null_randomized_effect(self):
        d,b,design=simulated_switchback(0)
        result,_=estimate_switchback(d,b,design)
        self.assertAlmostEqual(result["estimate"],0,places=6)
        self.assertGreater(result["p_signflip"],.95)

    def test_rejects_outcome_derived_treatment(self):
        d,b,design=simulated_switchback()
        b["assignment_source"]="inferred_from_tx_flushed"
        with self.assertRaises(ValueError):estimate_switchback(d,b,design)

    def test_shortened_clock_needs_explicit_alignment(self):
        d,b,design=simulated_switchback()
        d["session_time_s"]=np.nan
        with self.assertRaises(ValueError):estimate_switchback(d,b,design)
        design["stream_clock_offsets_s"]={s:0.0 for s in d.stream_id.unique()}
        result,_=estimate_switchback(d,b,design)
        self.assertAlmostEqual(result["estimate"],-30,places=6)

    def test_rejects_overlapping_treatment(self):
        d,b,design=simulated_switchback()
        b.loc[1,"start_s"]=10
        with self.assertRaises(ValueError):estimate_switchback(d,b,design)

    def test_rejects_unmatched_device_comparison(self):
        d=sle_frame(100);d["device_id"]="A"
        status,_=compare_devices(d,read_json(SKILL/"assets/wifi_adapter.json"))
        self.assertEqual(status["status"],"blocked")

if __name__=="__main__":
    unittest.main(verbosity=2)

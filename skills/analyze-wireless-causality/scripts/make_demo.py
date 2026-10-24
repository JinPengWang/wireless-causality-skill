"""Create clearly labeled synthetic Wi-Fi and randomized-switchback examples."""
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
from data_io import write_json
from causal import REQUIRED_ATTESTATIONS
def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() and any(a.output.iterdir()):raise ValueError("Choose an empty output")
    a.output.mkdir(parents=True,exist_ok=True)
    rows=[];blocks=[];rng=np.random.default_rng(20261023)
    for s in range(10):
        order=[0,1] if rng.integers(2) else [1,0]
        session=f"synthetic_run{s:02d}"
        for b,tr in enumerate(order):
            blocks.append({"session_id":"wifi|"+session+"|synthetic_lab","block_id":f"block{b}","pair_id":f"P{s:02d}",
                "start_s":b*60,"end_s":(b+1)*60,"treatment":tr,
                "assignment_source":"synthetic_independent_randomizer_seed20261023"})
        for dev,offset in [("A",0),("B",12)]:
            byte_count=0.;retries=0;failed=0
            for i in range(1201):
                t=i*.1;tr=order[0] if t<=60 else order[1]
                throughput=100+s+offset+(-30+.6*(s-4.5))*tr
                if i:byte_count+=throughput*1000/8*.1
                retries+=2*tr
                rows.append({"timestamp":(pd.Timestamp("2026-01-01",tz="UTC")+pd.Timedelta(seconds=s*300+t)).isoformat(),
                  "device_id":dev,"session_id":session,"scenario":"synthetic_lab","link_id":"wlan0",
                  "app_rx_bytes_total":byte_count,"rssi_dbm":-55+rng.normal(0,.2),
                  "phy_rate_mbps":300,"channel_busy_pct":10+60*tr,
                  "tx_retries_total":retries,"tx_failed_total":failed,"app_latency_ms":3+8*tr,
                  "pair_id":f"P{s:02d}","firmware":"synthetic_v1","band_ghz":2.4,
                  "channel_width_mhz":20,"offered_load_mbps":1.0})
    pd.DataFrame(rows).to_csv(a.output/"synthetic_wifi.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(blocks).to_csv(a.output/"synthetic_interventions.csv",index=False,encoding="utf-8-sig")
    design={x:True for x in REQUIRED_ATTESTATIONS}
    design.update({"design":"randomized_paired_switchback","estimand":"Synthetic session-average ON minus OFF",
      "treatment_definition":"synthetic external interference switch","outcome":"throughput_kbps",
      "randomization_protocol":"synthetic paired order, seed20261023","population":"synthetic data only",
      "washout_s":3.0,"min_coverage":.8})
    write_json(a.output/"synthetic_design.json",design)
    write_json(a.output/"synthetic_ground_truth.json",{"SYNTHETIC_ONLY":True,
      "mean_intervention_effect_kbps":-30,"matched_device_B_minus_A_kbps":12,
      "independent_sessions":10,"warning":"Software validation only, not evidence about real SLE or Wi-Fi performance"})
    print(str(a.output.resolve()))
if __name__=="__main__":main()

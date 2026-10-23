"""Offline command-line entry point. Run --help; never mutates source files."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import platform
import shutil
import sys
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from data_io import read_json,write_json,sha256,inventory,load_sle,load_mapped_csv,aggregate_blocks
from diagnostics import summarize,detect_events,lag_screen,evidence_cards,compare_devices
from causal import causal_gate,estimate_switchback
from reporting import make_figures,write_report

SKILL=Path(__file__).resolve().parents[1]
def parser():
    p=argparse.ArgumentParser(description="通信异常定位、根因证据筛选与有门槛的因果分析")
    p.add_argument("--protocol",choices=["sle","wifi"],default="sle")
    p.add_argument("--data-root",type=Path)
    p.add_argument("--input",type=Path,help="mapped Wi-Fi CSV")
    p.add_argument("--adapter",type=Path)
    p.add_argument("--request",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--task",choices=["overview","diagnose","compare","causal"],default="diagnose")
    p.add_argument("--device-registry",type=Path)
    p.add_argument("--interventions",type=Path)
    p.add_argument("--design",type=Path)
    p.add_argument("--seed",type=int,default=20261023)
    p.add_argument("--no-plots",action="store_true")
    return p

def apply_registry(d,path):
    r=pd.read_csv(path,dtype={"hdl":str})
    keys=["dataset","condition","segment","hdl"]
    if any(k not in r for k in keys+["device_id"]):raise ValueError("Device registry missing key columns")
    if r.duplicated(keys).any():raise ValueError("Device registry keys must be unique")
    if r[keys+["device_id"]].isna().any().any():raise ValueError("Incomplete device mapping")
    d=d.copy();d["hdl"]=d.hdl.astype(str)
    r["hdl"]=r.hdl.astype(str)
    extras=[c for c in r if c not in keys]
    d=d.drop(columns=[c for c in extras if c in d])
    d=d.merge(r,on=keys,how="left",validate="many_to_one",sort=False)
    return d

def main(argv=None):
    args=parser().parse_args(argv)
    code_initial=inventory(list((SKILL/"scripts").glob("*.py")),SKILL)
    adapter_path=args.adapter or SKILL/"assets"/(args.protocol+"_adapter.json")
    adapter=read_json(adapter_path)
    if adapter["protocol"]!=args.protocol:raise ValueError("Adapter protocol does not match --protocol")
    request=read_json(args.request) if args.request else {}
    cfg={"dip_fraction":request.get("dip_fraction",.5),"min_event_seconds":request.get("min_event_seconds",.3),
         "block_seconds":request.get("block_seconds",1.0),"min_coverage":request.get("min_coverage",.8),
         "lag_seconds":request.get("lag_seconds",[-1,0,1,2,5])}
    if cfg["block_seconds"]!=1:raise ValueError("v1 lag diagnostics require 1-second blocks")
    if not 0<cfg["dip_fraction"]<1 or cfg["min_event_seconds"]<=0 or not 0<cfg["min_coverage"]<=1:
        raise ValueError("Invalid event/coverage thresholds")
    if any(not isinstance(x,int) or abs(x)>30 for x in cfg["lag_seconds"]):raise ValueError("Lags must be integer seconds within +/-30")
    out=args.output.resolve()
    if out.exists() and any(out.iterdir()):raise ValueError("Output directory must be empty; choose a new run directory")
    if args.protocol=="sle":
        if not args.data_root:raise ValueError("--data-root is required for SLE")
        root=args.data_root.resolve()
        # Capture hashes before processing, and compare after all processing.
        source_paths=[p for folder in adapter["dataset_dirs"] for p in (root/folder).iterdir() if p.suffix in [".csv",".json",".npz"]]
        source_paths += [p for p in [root/"SLE参数对照表_0813.xlsx",root/"场景介绍.png"] if p.exists()]
        initial=inventory(source_paths,root)
        d,audit,quality,npz,paths=load_sle(root,adapter)
    else:
        if not args.input:raise ValueError("--input is required for Wi-Fi")
        root=args.input.resolve().parent
        initial=inventory([args.input.resolve()],root)
        d,audit,quality,npz,paths=load_mapped_csv(args.input,adapter)
    extra_inputs=[p.resolve() for p in [adapter_path,args.request,args.device_registry,args.interventions,args.design] if p]
    extra_initial=inventory(extra_inputs,root)
    if args.device_registry:d=apply_registry(d,args.device_registry)
    summary=summarize(d)
    events,annotated=detect_events(d,drop_fraction=cfg["dip_fraction"],min_duration=cfg["min_event_seconds"])
    blocks=aggregate_blocks(d,seconds=cfg["block_seconds"],min_coverage=cfg["min_coverage"])
    outcomes=[x for x in ["throughput_kbps","stall_flag"] if x in blocks]
    if args.task!="overview":
        screen=lag_screen(blocks,adapter["causal_candidates"],outcomes,seed=args.seed,lags=cfg["lag_seconds"])
    else:screen=pd.DataFrame(columns=["feature","outcome","lag_s"])
    cards=evidence_cards(screen,events,adapter)
    comparison,pairs=compare_devices(d,adapter,seed=args.seed)
    causal=causal_gate()
    treatment_blocks=pd.DataFrame()
    if bool(args.interventions)!=bool(args.design):raise ValueError("--interventions and --design must be supplied together")
    if args.interventions:
        causal,treatment_blocks=estimate_switchback(d,pd.read_csv(args.interventions),read_json(args.design),args.seed)
    sensitivity=[]
    for threshold in [.3,.5,.7]:
        ev,_=detect_events(d,drop_fraction=threshold,min_duration=cfg["min_event_seconds"])
        for dataset in d.dataset.unique():
            sub=ev[(ev.dataset==dataset)&(ev.kind=="throughput_dip")]
            sensitivity.append({"dataset":dataset,"drop_fraction":threshold,"events":len(sub),
                "observed_event_seconds":sub.observed_duration_s.sum() if len(sub) else 0,
                "meaning":"threshold_sensitivity_not_causal_replication"})
    out.mkdir(parents=True,exist_ok=True);tables=out/"tables";tables.mkdir()
    frames={"data_quality":audit,"channel_coverage":quality,"npz_audit":npz,
      "stream_summary":summary,"events":events,"lag_associations":screen,
      "matched_device_pairs":pairs,"treatment_block_outcomes":treatment_blocks,
      "event_sensitivity":pd.DataFrame(sensitivity),"one_second_blocks":blocks}
    for name,frame in frames.items():
        if len(frame.columns):frame.to_csv(tables/(name+".csv"),index=False,encoding="utf-8-sig")
    write_json(tables/"evidence_cards.json",cards)
    write_json(tables/"causal_status.json",causal)
    write_json(tables/"comparison_status.json",comparison)
    plots=[] if args.no_plots else make_figures(annotated,summary,events,blocks,screen,quality,out/"figures")
    unchanged=initial==inventory(source_paths if args.protocol=="sle" else [args.input.resolve()],root)
    extra_unchanged=extra_initial==inventory(extra_inputs,root)
    if not unchanged or not extra_unchanged:raise RuntimeError("An input changed during analysis; run invalid")
    if code_initial!=inventory(list((SKILL/"scripts").glob("*.py")),SKILL):raise RuntimeError("Analysis code changed during run; rerun from a stable version")
    versions={}
    for lib in ["numpy","pandas","scipy","matplotlib","openpyxl"]:
        try:versions[lib]=importlib.metadata.version(lib)
        except importlib.metadata.PackageNotFoundError:versions[lib]="unavailable"
    manifest={"schema_version":"1.0","skill":"analyze-wireless-causality","skill_version":"1.0.0",
      "generated_utc":datetime.now(timezone.utc).isoformat(),"protocol":args.protocol,"task":args.task,
      "seed":args.seed,"settings":cfg,"python":platform.python_version(),"libraries":versions,
      "sources":initial,"analysis_inputs":extra_initial,"source_files_unchanged":unchanged and extra_unchanged,
      "code":code_initial,
      "source_rows":len(d),"events":len(events),"association_tests":len(screen),
      "causal_status":causal["status"],"notes":["No private inputs were transmitted by the pipeline","No treatment labels were inferred","No independent device identity inferred from handles"]}
    write_json(out/"manifest.json",manifest)
    write_json(out/"resolved_adapter.json",adapter)
    write_report(out,annotated,audit,quality,npz,summary,events,screen,cards,comparison,causal,plots,manifest)
    print(json.dumps({"report":str(out/"report.html"),"rows":len(d),"events":len(events),
      "tests":len(screen),"source_files_unchanged":unchanged,"causal_status":causal["status"]},ensure_ascii=False))
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,RuntimeError) as e:
        print("ANALYSIS_BLOCKED: "+str(e),file=sys.stderr);sys.exit(2)


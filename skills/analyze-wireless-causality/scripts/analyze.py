"""Question-driven offline investigation entry point. Python >=3.9."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import platform
import sys
from datetime import datetime,timezone
import pandas as pd
from data_io import read_json,write_json,inventory,load_sle,load_mapped_csv,aggregate_blocks
from diagnostics import summarize,lag_screen
from causal import causal_gate,estimate_switchback
from request_contract import fingerprint,resolve_request,scope_data,capability_assessment,validate_adapter,measurement_profiles
from case_engine import detect_target_events,build_casebook,diff_casebooks
from comparison import compare_cohort
from reporting import make_figures,make_case_figures,write_investigation_report

SKILL=Path(__file__).resolve().parents[1]
def parser():
    p=argparse.ArgumentParser(description="问题驱动的通信专家调查与证据闭环")
    p.add_argument("--protocol",help="sle, wifi, or protocol declared by a supplied adapter")
    p.add_argument("--data-root",type=Path)
    p.add_argument("--input",type=Path)
    p.add_argument("--adapter",type=Path)
    p.add_argument("--request",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--task",choices=["overview","diagnose","compare","causal"])
    p.add_argument("--device-registry",type=Path)
    p.add_argument("--interventions",type=Path)
    p.add_argument("--design",type=Path)
    p.add_argument("--previous-run",type=Path,help="Read a prior casebook for evidence revision; never overwrite it")
    p.add_argument("--seed",type=int)
    p.add_argument("--no-plots",action="store_true")
    return p

def apply_registry(d,path):
    r=pd.read_csv(path,dtype={"hdl":str})
    keys=["dataset","condition","segment","hdl"]
    if any(k not in r for k in keys+["device_id"]):raise ValueError("Device registry missing key columns")
    if r.duplicated(keys).any():raise ValueError("Device registry keys must be unique")
    if r[keys+["device_id"]].isna().any().any():raise ValueError("Incomplete device mapping")
    d=d.copy();d["hdl"]=d.hdl.astype(str);r["hdl"]=r.hdl.astype(str)
    extras=[c for c in r if c not in keys]
    d=d.drop(columns=[c for c in extras if c in d])
    return d.merge(r,on=keys,how="left",validate="many_to_one",sort=False)

def main(argv=None):
    args=parser().parse_args(argv);code_initial=inventory(list((SKILL/"scripts").glob("*.py")),SKILL)
    protocol=args.protocol or "sle"
    if not args.adapter and protocol not in {"sle","wifi"}:raise ValueError("A new protocol requires --adapter")
    adapter_path=(args.adapter or SKILL/"assets"/(protocol+"_adapter.json")).resolve()
    adapter=validate_adapter(read_json(adapter_path))
    if args.protocol and adapter["protocol"]!=args.protocol:raise ValueError("Adapter protocol does not match --protocol")
    contract=resolve_request(read_json(args.request) if args.request else {},adapter,args.task,args.seed)
    out=args.output.resolve()
    if out.exists() and any(out.iterdir()):raise ValueError("Output directory must be empty")
    if bool(args.interventions)!=bool(args.design):raise ValueError("--interventions and --design must be supplied together")
    if args.interventions and contract["task"]!="causal":raise ValueError("Intervention estimation requires task=causal")
    catalog_path=SKILL/"assets/hypothesis_catalog.json";catalog=read_json(catalog_path)
    extra_inputs=[p.resolve() for p in [adapter_path,catalog_path,args.request,args.device_registry,args.interventions,args.design] if p]
    previous=None
    if args.previous_run:
        prior=args.previous_run/"tables/casebook.json"
        previous=read_json(prior);extra_inputs.append(prior.resolve())
    if adapter["loader"]=="sle_bundle":
        if not args.data_root:raise ValueError("--data-root is required by sle_bundle")
        root=args.data_root.resolve()
        source_paths=[p for folder in adapter["dataset_dirs"] for p in (root/folder).iterdir() if p.suffix in [".csv",".json",".npz"]]
        source_paths += [p for p in [root/"SLE参数对照表_0813.xlsx",root/"场景介绍.png"] if p.exists()]
        initial=inventory(source_paths,root);extra_initial=inventory(extra_inputs,root)
        loaded,audit,quality,npz,_=load_sle(root,adapter)
    else:
        if not args.input:raise ValueError("--input is required by mapped_csv")
        root=args.input.resolve().parent;source_paths=[args.input.resolve()]
        initial=inventory(source_paths,root);extra_initial=inventory(extra_inputs,root)
        loaded,audit,quality,npz,_=load_mapped_csv(args.input,adapter)
    if args.device_registry:loaded=apply_registry(loaded,args.device_registry)
    d=scope_data(loaded,contract)
    summary=summarize(d);capabilities=capability_assessment(d,contract)
    events=pd.DataFrame();screen=pd.DataFrame();blocks=pd.DataFrame();profiles=pd.DataFrame()
    casebook={"schema_version":"2.0","contract_id":contract["contract_id"],"case_count":0,"cases":[]}
    comparison={"status":"not_requested"};pairs=pd.DataFrame()
    causal={"status":"not_requested","causal_effect":None};treatment_blocks=pd.DataFrame();sensitivity=[]
    if contract["task"]=="diagnose":
        events,d=detect_target_events(d,contract)
        roles=adapter.get("diagnostic_roles",{})
        count_fields=adapter.get("count_metrics",["abnormal_cnt","cancel_cnt","abort_cnt","retry_count","failure_count"])
        blocks=aggregate_blocks(d,min_coverage=contract["min_coverage"],extra_metrics=contract["candidate_causes"],count_metrics=count_fields)
        screen=lag_screen(blocks,contract["candidate_causes"],[contract["primary_outcome"]],
            seed=contract["seed"],lags=contract["lag_seconds"])
        profiles=measurement_profiles(d,contract["candidate_causes"])
        casebook=build_casebook(d,events,screen,contract,adapter,catalog)
        causal=causal_gate()
        if contract["detector"]["mode"]=="relative":
            from copy import deepcopy
            for threshold in [.3,.5,.7]:
                variant=deepcopy(contract);variant["detector"]["drop_fraction"]=threshold
                ev,_=detect_target_events(d,variant)
                for dataset in d.dataset.unique():
                    q=ev[ev.dataset.eq(dataset)] if len(ev) else ev
                    sensitivity.append({"dataset":dataset,"drop_fraction":threshold,"events":len(q),
                        "observed_event_seconds":q.observed_duration_s.sum() if len(q) else 0,
                        "meaning":"threshold_sensitivity_not_causal_replication"})
    elif contract["task"]=="compare":
        comparison,pairs=compare_cohort(d,contract,adapter,contract["seed"])
    elif contract["task"]=="causal":
        causal=causal_gate()
        if args.interventions:
            causal,treatment_blocks=estimate_switchback(d,pd.read_csv(args.interventions),read_json(args.design),contract["seed"])
    casebook["code_fingerprint"]=fingerprint(code_initial)
    revision=diff_casebooks(previous,casebook) if previous is not None else {"status":"no_previous_casebook"}
    out.mkdir(parents=True,exist_ok=True);tables=out/"tables";tables.mkdir()
    frames={"data_quality":audit,"channel_coverage":quality,"npz_audit":npz,"stream_summary":summary,
      "events":events,"lag_associations":screen,"matched_device_pairs":pairs,
      "mechanism_contrasts":pd.DataFrame(comparison.get("mechanism_observations",[])),
      "treatment_block_outcomes":treatment_blocks,"event_sensitivity":pd.DataFrame(sensitivity),
      "one_second_blocks":blocks,"measurement_profiles":profiles}
    for name,frame in frames.items():
        if len(frame.columns):frame.to_csv(tables/(name+".csv"),index=False,encoding="utf-8-sig")
    for name,value in {"casebook":casebook,"evidence_revision":revision,"capabilities":capabilities,
                       "causal_status":causal,"comparison_status":comparison}.items():
        write_json(tables/(name+".json"),value)
    write_json(out/"resolved_request.json",contract);write_json(out/"resolved_adapter.json",adapter)
    plots=[]
    if not args.no_plots:
        if contract["task"]=="diagnose" and casebook["case_count"]:
            plots=make_case_figures(d,casebook,adapter,out/"figures")
        elif d.throughput_kbps.notna().any():
            plots=make_figures(d,summary,events,blocks,screen,quality,out/"figures")
    if initial!=inventory(source_paths,root) or extra_initial!=inventory(extra_inputs,root):
        raise RuntimeError("An input changed during analysis; run invalid")
    if code_initial!=inventory(list((SKILL/"scripts").glob("*.py")),SKILL):raise RuntimeError("Code changed during run")
    versions={}
    for lib in ["numpy","pandas","scipy","matplotlib"]:
        try:versions[lib]=importlib.metadata.version(lib)
        except importlib.metadata.PackageNotFoundError:versions[lib]="unavailable"
    manifest={"schema_version":"2.0","skill":"analyze-wireless-causality","skill_version":"2.0.0",
      "generated_utc":datetime.now(timezone.utc).isoformat(),"protocol":adapter["protocol"],"task":contract["task"],
      "seed":contract["seed"],"settings":contract,"python":platform.python_version(),"libraries":versions,
      "sources":initial,"analysis_inputs":extra_initial,"source_files_unchanged":True,"code":code_initial,
      "source_rows":len(d),"loaded_source_rows":len(loaded),"events":len(events),"association_tests":len(screen),
      "case_count":casebook["case_count"],"causal_status":causal["status"],"contract_id":contract["contract_id"],
      "notes":["No private inputs transmitted","No treatment labels inferred","No independent device identity inferred from handles",
               "Source audits describe all loaded inputs; diagnostics use resolved scope"]}
    write_json(out/"manifest.json",manifest)
    write_investigation_report(out,d,summary,casebook,capabilities,comparison,causal,plots,manifest)
    print(json.dumps({"output":str(out),"task":contract["task"],"scope_rows":len(d),"events":len(events),
      "cases":casebook["case_count"],"association_tests":len(screen),"comparison_status":comparison["status"],
      "causal_status":causal["status"],"source_files_unchanged":True},ensure_ascii=False))
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,RuntimeError) as e:
        print("ANALYSIS_BLOCKED: "+str(e),file=sys.stderr);sys.exit(2)

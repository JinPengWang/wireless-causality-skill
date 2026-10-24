"""Resolve an executable investigation contract. Reject silently ignored options."""
from copy import deepcopy
import hashlib
import json
import numpy as np
import pandas as pd

TASKS={"overview","diagnose","compare","causal"}
SCOPE_FIELDS={"dataset","condition","segment","hdl","device_id","stream_id"}
TOP_FIELDS={"schema_version","task","protocol","question","primary_outcome","scope","focus",
 "detector","reference","case_budget","candidate_causes","seed","lag_seconds","min_coverage",
 "block_seconds","comparison","causal_question","notes","dip_fraction","min_event_seconds"}
OUTCOMES={"throughput_kbps","stall_flag","latency_ms"}

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _bounded_number(value,name,low,high,low_inclusive=True):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not np.isfinite(value):
        raise ValueError(name+" must be a finite number")
    if (value<low if low_inclusive else value<=low) or value>high:raise ValueError(name+" out of range")
    return float(value)

def _unknown(d,allowed,label):
    if not isinstance(d,dict):raise ValueError(label+" must be an object")
    extra=set(d)-set(allowed)
    if extra:raise ValueError("Unknown "+label+" fields: "+", ".join(sorted(extra)))

def resolve_request(request,adapter,task=None,seed=None):
    _unknown(request,TOP_FIELDS,"request")
    r=deepcopy(request)
    if r.get("schema_version","2.0") not in {"1.0","2.0"}:raise ValueError("Unsupported request schema_version")
    # Accept the original template without pretending its legacy task is a CLI task.
    requested_task=r.get("task","diagnose")
    if requested_task=="throughput_dip":requested_task="diagnose"
    if task and "task" in r and task!=requested_task:raise ValueError("CLI task conflicts with request.task")
    selected_task=task or requested_task
    if selected_task not in TASKS:raise ValueError("Unsupported task")
    if r.get("protocol",adapter["protocol"])!=adapter["protocol"]:raise ValueError("Request protocol differs from adapter")
    outcome=r.get("primary_outcome",adapter.get("default_outcome","throughput_kbps"))
    if outcome not in OUTCOMES:raise ValueError("Unsupported primary_outcome; choose throughput_kbps, stall_flag or latency_ms")
    for name in ["question","causal_question","notes"]:
        if name in r and not isinstance(r[name],str):raise ValueError(name+" must be text")
    scope=r.get("scope",{});_unknown(scope,SCOPE_FIELDS,"scope")
    for k,v in scope.items():
        if not isinstance(v,list) or not v or any(isinstance(x,(dict,list)) or x is None for x in v):
            raise ValueError("scope."+k+" must be a nonempty list of exact values")
    focus=r.get("focus",{})
    _unknown(focus,{"event_id","stream_id","start_s","end_s"},"focus")
    if focus:
        if "event_id" in focus:
            if set(focus)!={"event_id"} or not isinstance(focus["event_id"],str):raise ValueError("focus.event_id is exclusive")
        else:
            if set(focus)!={"stream_id","start_s","end_s"} or not isinstance(focus["stream_id"],str):
                raise ValueError("Manual focus needs stream_id,start_s,end_s")
            for k in ["start_s","end_s"]:_bounded_number(focus[k],"focus."+k,0,1e9)
            if focus["end_s"]<=focus["start_s"]:raise ValueError("Empty focus interval")
    det=r.get("detector",{})
    _unknown(det,{"mode","drop_fraction","min_duration_s","baseline_s","min_history_reports","absolute_threshold"},"detector")
    default_mode="binary" if outcome=="stall_flag" else "absolute" if outcome=="latency_ms" else "relative"
    detector={"mode":det.get("mode",default_mode),"drop_fraction":det.get("drop_fraction",r.get("dip_fraction",.5)),
      "min_duration_s":det.get("min_duration_s",r.get("min_event_seconds",.3)),
      "baseline_s":det.get("baseline_s",10.0),"min_history_reports":det.get("min_history_reports",30),
      "absolute_threshold":det.get("absolute_threshold")}
    if detector["mode"] not in {"relative","absolute","binary"}:raise ValueError("Invalid detector.mode")
    if detector["mode"]=="binary" and outcome!="stall_flag":raise ValueError("Binary detector requires stall_flag")
    if detector["mode"]=="relative" and outcome!="throughput_kbps":raise ValueError("Relative detector currently supports throughput_kbps")
    detector["drop_fraction"]=_bounded_number(detector["drop_fraction"],"drop_fraction",0,1,False)
    if detector["drop_fraction"]>=1:raise ValueError("drop_fraction must be below 1")
    for name in ["min_duration_s","baseline_s"]:detector[name]=_bounded_number(detector[name],name,0,3600,False)
    if not isinstance(detector["min_history_reports"],int) or isinstance(detector["min_history_reports"],bool) or detector["min_history_reports"]<1:
        raise ValueError("min_history_reports must be a positive integer")
    if detector["mode"]=="absolute":_bounded_number(detector["absolute_threshold"],"absolute_threshold",0,1e9)
    reference=r.get("reference",{})
    if isinstance(reference,str):
        if reference!="past_10_seconds_within_stream":raise ValueError("Unknown legacy reference policy")
        reference={}
    _unknown(reference,{"window_s","lookback_s","guard_s","step_s","min_coverage","match_fields"},"reference")
    ref={"window_s":reference.get("window_s",10.0),"lookback_s":reference.get("lookback_s",120.0),
         "guard_s":reference.get("guard_s",2.0),"step_s":reference.get("step_s",2.0),
         "min_coverage":reference.get("min_coverage",.8),
         "match_fields":reference.get("match_fields",adapter.get("diagnostic_match_fields",[]))}
    for k in ["window_s","lookback_s","step_s"]:ref[k]=_bounded_number(ref[k],"reference."+k,0,3600,False)
    ref["guard_s"]=_bounded_number(ref["guard_s"],"reference.guard_s",0,3600)
    ref["min_coverage"]=_bounded_number(ref["min_coverage"],"reference.min_coverage",0,1,False)
    if ref["lookback_s"]<ref["window_s"]+ref["guard_s"]:raise ValueError("Reference lookback is too short")
    if not isinstance(ref["match_fields"],list) or any(not isinstance(x,str) for x in ref["match_fields"]):
        raise ValueError("reference.match_fields must contain column names")
    reserved=set(adapter.get("exclusions_from_causes",[]))|{"throughput_kbps","stall_flag","latency_ms","delay_proxy_ms","ack_ratio","device_id","source_row","time_s"}
    candidates=r.get("candidate_causes",adapter["causal_candidates"])
    if not isinstance(candidates,list) or any(not isinstance(x,str) for x in candidates):raise ValueError("candidate_causes must be names")
    if set(candidates)&reserved:raise ValueError("Identity, outcome or mediator used as candidate cause: "+str(sorted(set(candidates)&reserved)))
    if set(candidates)-set(adapter["causal_candidates"]):raise ValueError("Candidate is not declared by the protocol adapter")
    lag=r.get("lag_seconds",[-1,0,1,2,5])
    if not isinstance(lag,list) or any(not isinstance(x,int) or isinstance(x,bool) or abs(x)>30 for x in lag):raise ValueError("Lags must be integer seconds within +/-30")
    if not {-1,0,1}.issubset(set(lag)):raise ValueError("Include -1,0,1 seconds to retain symmetric direction checks")
    if r.get("block_seconds",1)!=1:raise ValueError("Lag diagnostics require 1-second blocks")
    comparison=r.get("comparison",{})
    _unknown(comparison,{"reference_device","target_devices","metrics","match_fields"},"comparison")
    comp={"reference_device":comparison.get("reference_device"),"target_devices":comparison.get("target_devices",[]),
          "metrics":comparison.get("metrics",[outcome]),"match_fields":comparison.get("match_fields",adapter.get("matched_covariates",[]))}
    if comp["reference_device"] is not None and not isinstance(comp["reference_device"],str):raise ValueError("reference_device must be text")
    for name in ["target_devices","metrics","match_fields"]:
        if not isinstance(comp[name],list) or any(not isinstance(x,str) for x in comp[name]):raise ValueError("comparison."+name+" must be a list of names")
    if any(len(v)!=len(set(v)) for v in [comp["metrics"],comp["match_fields"],comp["target_devices"],ref["match_fields"]]):raise ValueError("Duplicate names in comparison or reference")
    if "device_id" in comp["match_fields"]:raise ValueError("Cannot match devices on device_id")
    if not comp["metrics"] or set(comp["metrics"])-OUTCOMES:raise ValueError("Unsupported comparison metrics")
    if "pair_id" not in comp["match_fields"]:raise ValueError("comparison.match_fields must include pair_id")
    if set(comp["metrics"])&set(comp["match_fields"]):raise ValueError("Cannot match on the result being compared")
    if set(ref["match_fields"])&OUTCOMES:raise ValueError("Cannot require an equal primary outcome in the reference")
    chosen_seed=seed if seed is not None else r.get("seed",20261023)
    if not isinstance(chosen_seed,int) or isinstance(chosen_seed,bool) or not 0<=chosen_seed<2**32:raise ValueError("Invalid seed")
    budget=r.get("case_budget",6)
    if not isinstance(budget,int) or isinstance(budget,bool) or not 1<=budget<=30:raise ValueError("case_budget must be 1..30")
    resolved={"schema_version":"2.0","task":selected_task,"protocol":adapter["protocol"],
       "question":r.get("question","分析通信数据中的异常及竞争解释"),"primary_outcome":outcome,
       "scope":scope,"focus":focus,"detector":detector,"reference":ref,"case_budget":budget,
       "candidate_causes":list(dict.fromkeys(candidates)),"seed":chosen_seed,"block_seconds":1,
       "min_coverage":_bounded_number(r.get("min_coverage",.8),"min_coverage",0,1,False),
       "lag_seconds":sorted(set(lag)),"comparison":comp,
       "causal_question":r.get("causal_question",""),"notes":r.get("notes","")}
    resolved["contract_id"]=fingerprint(resolved)[:16]
    return resolved

def scope_data(d,contract):
    selected=d
    for field,values in contract["scope"].items():
        if field not in selected:raise ValueError("Scope column missing: "+field)
        available=set(selected[field].dropna().astype(str))
        if set(map(str,values))-available:raise ValueError("Scope values unavailable for "+field)
        selected=selected[selected[field].astype(str).isin(list(map(str,values)))]
    if selected.empty:raise ValueError("Investigation scope is empty")
    if contract["task"]!="overview" and (contract["primary_outcome"] not in selected or not selected[contract["primary_outcome"]].notna().any()):
        raise ValueError("No measured primary outcome in scope: "+contract["primary_outcome"])
    focus=contract["focus"]
    if focus and "stream_id" in focus and focus["stream_id"] not in set(selected.stream_id):
        raise ValueError("Focused stream is outside the population")
    return selected.copy()

def capability_assessment(d,contract):
    roles={"primary_outcome":[contract["primary_outcome"]],"candidate_observations":contract["candidate_causes"],
           "workload":["tx_total","offered_load_mbps"],"identity":["device_id"]}
    fields=[]
    for role,names in roles.items():
        for name in names:
            series=d[name] if name in d else pd.Series(dtype=float)
            n=int(series.notna().sum())
            fields.append({"role":role,"field":name,"observed_rows":n,"distinct_values":int(series.nunique()),
              "status":"absent" if n==0 else "constant" if series.nunique()<2 else "available"})
    return {"scope_rows":len(d),"scope_streams":int(d.stream_id.nunique()),"fields":fields,
      "task_plan":{"overview":["audit","stratified_summary"],
        "diagnose":["audit","events","within_stream_lags","event_cases","competing_hypotheses"],
        "compare":["audit","common_support","paired_device_contrasts"],
        "causal":["audit","identification_gate","conditional_estimation_if_eligible"]}[contract["task"]],
      "causal_identification":"requires_external_design",
      "workload_warning":"tx_total是发包记录，offered_load_mbps可能只是配置；均不能自动证明应用队列需求"}


def validate_adapter(adapter):
    if not isinstance(adapter.get("protocol"),str) or not adapter["protocol"]:raise ValueError("Adapter protocol required")
    if adapter.get("loader") not in {"sle_bundle","mapped_csv"}:raise ValueError("Unsupported adapter loader")
    if not isinstance(adapter.get("causal_candidates"),list):raise ValueError("Declare causal_candidates")
    if not isinstance(adapter.get("diagnostic_roles",{}),dict):raise ValueError("Invalid diagnostic roles")
    interval=adapter.get("interval",{})
    for field in ["nominal_s","min_rate_s","gap_s"]:_bounded_number(interval.get(field),"interval."+field,0,3600,False)
    if interval["min_rate_s"]>interval["gap_s"]:raise ValueError("Invalid interval range")
    if adapter["loader"]=="mapped_csv":
        identity=adapter.get("identity",{})
        if any(x not in identity for x in ["timestamp","device","session","scenario","link"]):raise ValueError("Incomplete identity mapping")
        kinds={"gauge","cumulative_count","cumulative_bytes","interval_count","interval_bytes"}
        metrics=adapter.get("metrics",{})
        if not metrics:raise ValueError("Declare metric mappings")
        for name,spec in metrics.items():
            if spec.get("kind") not in kinds or not isinstance(spec.get("source"),str):raise ValueError("Invalid metric mapping: "+name)
            if spec.get("kind")!="gauge" and spec.get("unit")!=("byte" if "bytes" in spec["kind"] else "count"):raise ValueError("Counter kind and unit disagree")
            if "scale" in spec:_bounded_number(spec["scale"],"metric.scale",0,1e9,False)
    return adapter

def measurement_profiles(d,fields):
    rows=[]
    for stream,g in d.groupby("stream_id",sort=False):
        g=g.sort_values("time_s",kind="stable")
        for field in fields:
            if field not in g:continue
            known=g[field].notna()
            if not known.any():continue
            changed=known & g[field].ne(g[field].shift()) & g[field].shift().notna()
            change_times=g.loc[changed,"time_s"]
            gaps=change_times.diff().dropna()
            rows.append({"stream_id":stream,"field":field,"observed_reports":int(known.sum()),
                "value_changes":int(changed.sum()),"distinct_values":int(g[field].nunique()),
                "median_between_value_changes_s":float(gaps.median()) if len(gaps) else None,
                "constant_report_fraction":float((known&g[field].eq(g[field].shift())).sum()/known.sum()),
                "interpretation":"unchanged_printed_value_not_proof_of_sensor_update_period"})
    return pd.DataFrame(rows)

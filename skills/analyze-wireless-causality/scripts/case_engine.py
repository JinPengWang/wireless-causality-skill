"""Event-scoped evidence: fixed reference policy, exact source rows, no causal claims."""
import hashlib
import numpy as np
import pandas as pd

def _finite(x):
    return x is not None and np.isfinite(x)

def _weighted(q,col):
    if col not in q:return None
    valid=q.valid_rate_interval&q[col].notna()
    if not valid.any():return None
    return float(q.loc[valid,col].iloc[0]) if q.loc[valid,col].nunique()==1 else float(np.average(q.loc[valid,col],weights=q.loc[valid,"dt"]))

def window_summary(q,adapter):
    good=q.valid_rate_interval
    out={"n_reports":len(q),"valid_seconds":float(q.loc[good,"dt"].sum()),
      "source_refs":[{"file":str(file),"rows":[int(x) for x in z.source_row],
                     "stream_id":str(z.stream_id.iloc[0]),"piece":int(z.piece.iloc[0])}
                    for file,z in q.groupby("source_file",sort=False)],
      "metrics":{}}
    fields=list(dict.fromkeys(["throughput_kbps","stall_flag","ack_ratio","delay_proxy_ms","latency_ms"]+
        sum(adapter.get("diagnostic_roles",{}).values(),[])+adapter.get("causal_candidates",[])))
    count_fields=set(adapter.get("count_metrics",[]))|{"abnormal_cnt","cancel_cnt","abort_cnt","retry_count","failure_count"}
    for name in fields:
        val=_weighted(q,name)
        valid=q.valid_rate_interval & q[name].notna() if name in q else pd.Series(False,index=q.index)
        if name=="ack_ratio" and "tx_total" in q:
            valid&=q.tx_total.gt(0)&q.tx_ack.between(0,q.tx_total)
            val=float(q.loc[valid,"tx_ack"].sum()/q.loc[valid,"tx_total"].sum()) if valid.any() else None
        if name=="delay_proxy_ms" and "cnt_diff_total" in q:
            valid&=q.cnt_total_nb.gt(0)&q.cnt_diff_total.notna()
            val=float(adapter["counter_period_ms"]*q.loc[valid,"cnt_diff_total"].sum()/q.loc[valid,"cnt_total_nb"].sum()) if valid.any() else None
        if name in count_fields and valid.any():
            val=float(q.loc[valid,name].sum()/q.loc[valid,"dt"].sum())
        values=(q.loc[valid,name].div(q.loc[valid,"dt"]) if name in count_fields else q.loc[valid,name]).to_numpy(float) if valid.any() else np.array([])
        mad=float(np.median(np.abs(values-np.median(values)))) if len(values) else None
        out["metrics"][name]={"value":val,"mad":mad,"observed_rows":int(valid.sum()),
                              "aggregation":"count_per_second" if name in count_fields else "interval_weighted_or_count_ratio"}
    out["settings"]={}
    for c in list(dict.fromkeys(adapter.get("diagnostic_match_fields",[])+adapter.get("diagnostic_roles",{}).get("control",[]))):
        values=q[c].dropna().unique() if c in q else []
        out["settings"][c]=[x.item() if hasattr(x,"item") else x for x in values]
    if "tx_total" in q:
        known=q.tx_total.notna()
        out["no_tx_all_observed"]=bool(known.all() and len(q) and q.tx_total.eq(0).all())
    else:out["no_tx_all_observed"]=None
    out["counter_reset_reports"]=int(q.counter_reset.sum()) if "counter_reset" in q else None
    return out

def select_reference(g,event_rows,event,contract,adapter):
    """Nearest eligible past window; no search on hypothesized causes or effect size.
    Outcome-based 'clean' eligibility is diagnostic selection, never an ATE control."""
    policy=contract["reference"];event_start=float(event["start_s"])
    piece=g[g.piece.eq(event["piece"])]
    match=policy["match_fields"];missing=[x for x in match if x not in piece]
    varies=[x for x in match if x in event_rows and event_rows[x].dropna().nunique()>1]
    unknown=[x for x in match if x in event_rows and event_rows[x].isna().any()]
    unavailable={"status":"unavailable","source_refs":[],"selection":"nearest_eligible_past_window",
                 "selection_bias":"reference_selected_for_clean_outcome_not_a_causal_control"}
    if missing or unknown:return {**unavailable,"reason":"missing_match_settings","fields":missing+unknown},None
    if varies:return {**unavailable,"reason":"event_settings_vary","fields":varies},None
    duration=policy["window_s"];latest=event_start-policy["guard_s"]
    earliest=max(float(piece.time_s.min()),event_start-policy["lookback_s"])
    tried=0;reasons={}
    for end in np.arange(latest,earliest+duration-1e-8,-policy["step_s"]):
        start=float(end-duration);tried+=1
        q=piece[(piece.time_s-piece.dt>=start-1e-8)&(piece.time_s<=end+1e-8)]
        if not len(q):reason="empty"
        elif (q.time_s+1e-8>=event_start).any():reason="overlaps_event"
        elif q.loc[q.valid_rate_interval&q[contract["primary_outcome"]].notna(),"dt"].sum()/duration<policy["min_coverage"]:reason="low_coverage"
        elif "target_event" in q and q.target_event.fillna(False).any():reason="contains_detected_problem"
        elif "stall_flag" in q and q.stall_flag.fillna(0).gt(0).any():reason="contains_timeout"
        elif any(not q[c].notna().all() or not q[c].eq(event_rows[c].iloc[0]).all() for c in match):reason="setting_mismatch"
        elif "tx_total" in q and not q.tx_total.gt(0).any():reason="no_transmission"
        else:
            summary=window_summary(q,adapter)
            return {"status":"selected","start_s":start,"end_s":float(end),"candidates_examined":tried,"rejections":dict(reasons),
               "selection":"nearest_eligible_past_window","match_fields":match,
               "selection_bias":"reference_selected_for_clean_outcome_not_a_causal_control",
               **summary},q
        reasons[reason]=reasons.get(reason,0)+1
    return {**unavailable,"reason":"no_eligible_past_window","candidates_examined":tried,"rejections":reasons},None

def compare_metrics(event,reference,adapter):
    deltas={}
    for name,m in event["metrics"].items():
        r=reference.get("metrics",{}).get(name,{})
        a,b=m["value"],r.get("value")
        if not _finite(a) or not _finite(b):
            deltas[name]={"status":"unmeasured_or_no_reference","during":a,"reference":b};continue
        floor=float(adapter.get("diagnostic_thresholds",{}).get(name,0))
        noise=float(r.get("mad") or 0)*1.4826*2
        threshold=max(floor,noise,1e-9)
        diff=float(a-b)
        deltas[name]={"status":"up" if diff>=threshold else "down" if diff<=-threshold else "stable",
            "during":a,"reference":b,"difference":diff,"screening_threshold":threshold,
            "criterion":"max(configured_raw_unit_floor,2*1.4826*reference_MAD); exploratory_not_significance"}
    return deltas

def local_lag_evidence(screen,case,features,outcome):
    result={}
    if screen.empty:return result
    for feature in features:
        q=screen[(screen.stream_id==case["stream_id"])&(screen.piece==case["piece"])&
          (screen.feature==feature)&(screen.outcome==outcome)]
        # Do not choose the maximum over lags/runs: symmetric fixed +/-1s, same run.
        positives=q[q.lag_s.eq(1)]
        if positives.empty:continue
        for _,f in positives.iterrows():
            b=q[q.run.eq(f.run)&q.lag_s.eq(-1)]
            item={"feature":feature,"run":int(f.run),"lag_s":1,"rho_past":float(f.spearman_rho),
                  "detrended_rho":float(f.detrended_rho),"q_exploratory":float(f.q_shift_exploratory),
                  "scope":"same_stream_and_piece_context_not_event_specific","causal_identified":False}
            if len(b):
                future=float(b.iloc[0].spearman_rho)
                item["rho_future"]=future
                item["direction_warning"]=abs(future)>=max(abs(float(f.spearman_rho))-.05,0)
            else:item["direction_warning"]=True;item["warning"]="future_feature_control_unavailable"
            result.setdefault(feature,[]).append(item)
    return result

def choose_cases(events,d,contract):
    focus=contract["focus"]
    if focus and "event_id" in focus:
        q=events[events.event_id.eq(focus["event_id"])]
        if len(q)!=1:raise ValueError("Focused event was not detected within scope and current definition")
        return q.copy(),"explicit_event"
    if focus:
        g=d[d.stream_id.eq(focus["stream_id"])]
        q=g[(g.time_s-g.dt>=focus["start_s"]-1e-8)&g.time_s.le(focus["end_s"]+1e-8)]
        if not len(q):raise ValueError("No complete measurement intervals inside focus")
        if q.piece.nunique()!=1:raise ValueError("Focused case crosses a discontinuity; split the investigation")
        key=str((focus,contract["primary_outcome"]))
        row={"event_id":"window_"+hashlib.sha256(key.encode()).hexdigest()[:12],"kind":"manual_window",
          "stream_id":focus["stream_id"],"piece":int(q.piece.iloc[0]),"start_s":focus["start_s"],
          "end_s":focus["end_s"],"observed_duration_s":float(q.loc[q.valid_rate_interval,"dt"].sum()),
          "source_row_first":int(q.source_row.min()),"source_row_last":int(q.source_row.max())}
        for c in ["dataset","condition","segment","hdl"]:row[c]=q[c].iloc[0]
        return pd.DataFrame([row]),"explicit_window"
    if events.empty:return events.copy(),"no_events_no_health_claim"
    selected=events[events.kind.eq("target_event")].copy()
    if selected.empty:return selected,"no_target_events_no_health_claim"
    selected=selected.sort_values(["observed_duration_s","event_id"],ascending=[False,True],kind="stable")
    # Include symptom counterexamples before filling stream diversity; no cause labels are inferred.
    selected["_phenotype"]=["no_tx" if row.get("load_status")=="no_tx_load_unresolved" else "with_timeout" if row.get("timeout_present",False) else "other_measured_dip" for _,row in selected.iterrows()]
    first=selected.drop_duplicates("_phenotype").head(contract["case_budget"])
    remaining=selected[~selected.event_id.isin(first.event_id)]
    diverse=remaining[~remaining.stream_id.isin(first.stream_id)].drop_duplicates("stream_id")
    first=pd.concat([first,diverse.head(contract["case_budget"]-len(first))])
    remaining=selected[~selected.event_id.isin(first.event_id)]
    return pd.concat([first,remaining.head(contract["case_budget"]-len(first))]),"symptom_counterexamples_then_stream_diversity_then_duration"

def build_casebook(d,events,screen,contract,adapter,catalog):
    from hypothesis_engine import assess_hypotheses,decision_for_case
    chosen,selection=choose_cases(events,d,contract);cases=[]
    for _,e in chosen.iterrows():
        g=d[d.stream_id.eq(e.stream_id)]
        if "source_rows" in e and isinstance(e.source_rows,list):
            q=g[g.piece.eq(e.piece)&g.source_row.isin(e.source_rows)].copy()
        else:
            q=g[g.piece.eq(e.piece)&(g.time_s-g.dt>=float(e.start_s)-1e-8)&(g.time_s<=float(e.end_s)+1e-8)].copy()
        if not len(q):raise ValueError("Event trace resolves to no raw rows")
        summary=window_summary(q,adapter)
        ref,reference_rows=select_reference(g,q,e,contract,adapter)
        scope={c:str(e[c]) for c in ["dataset","condition","segment","hdl","stream_id"]}
        case={"case_id":str(e.event_id),"kind":str(e.kind),"piece":int(e.piece),**scope,
              "start_s":float(e.start_s),"end_s":float(e.end_s),
              "outcome":contract["primary_outcome"],"event":summary,"reference":ref,
              "metrics":compare_metrics(summary,ref,adapter),"evidence_level":"E1_maximum",
              "selection":"explicit" if contract["focus"] else "exploratory_case_selection",
              "independent_replication":False,"causal_effect":None}
        case["prelude"],case["configuration_phases"]=process_context(g,q,e,contract,adapter)
        case["trajectory_deltas"]=compare_metrics(summary,case["prelude"],adapter)
        clipped=case["kind"]=="manual_window" and case["prelude"].get("last_prior_report_already_alarm") is True
        case["onset_context"]={"focus_may_clip_existing_symptom":clipped,
           "warning":"人工焦点在已经发生的症状中，不能将焦点起点当作实际故障起点" if clipped else "检测或焦点边界不自动证明物理故障起点"}
        case["context_lags"]=local_lag_evidence(screen,case,contract["candidate_causes"],contract["primary_outcome"])
        case["hypotheses"]=assess_hypotheses(case,adapter,catalog)
        case["decision"]=decision_for_case(case)
        cases.append(case)
    return {"schema_version":"2.0","question":contract["question"],"contract_id":contract["contract_id"],
       "selection_policy":selection,"detected_events":len(events),"case_count":len(cases),"cases":cases,
       "interpretation":"case-specific diagnostic contrasts; selected healthy references are not counterfactual causal controls"}

def diff_casebooks(previous,current):
    def index(book):
        return {(c["stream_id"],c["kind"],c["start_s"],c["end_s"],c["outcome"]):c for c in book.get("cases",[])}
    old=index(previous);new=index(current);changes=[]
    for key,c in new.items():
        prior=old.get(key)
        if prior is None:changes.append({"case_id":c["case_id"],"change":"new_scope_or_new_case"});continue
        a={h["hypothesis_id"]:h["status"] for h in prior["hypotheses"]}
        for h in c["hypotheses"]:
            before=a.get(h["hypothesis_id"])
            if before!=h["status"]:changes.append({"case_id":c["case_id"],"hypothesis_id":h["hypothesis_id"],
                "before":before,"after":h["status"],"change":"diagnostic_evidence_revised_not_causal_confirmation"})
    for key,c in old.items():
        if key not in new:changes.append({"case_id":c["case_id"],"change":"not_in_current_scope_not_refuted"})
    return {"previous_contract_id":previous.get("contract_id"),"current_contract_id":current["contract_id"],
            "same_contract":previous.get("contract_id")==current["contract_id"],
            "same_code_snapshot":previous.get("code_fingerprint")==current.get("code_fingerprint") if previous.get("code_fingerprint") and current.get("code_fingerprint") else None,
            "changes":changes,
            "warning":"different code versions, scopes, thresholds, source versions or selection budgets can change cases; absence is not refutation"}


def detect_target_events(d,contract):
    """Configurable primary symptom; retain raw-row membership and continuous boundaries."""
    detector=contract["detector"];outcome=contract["primary_outcome"]
    events=[];annotated=[]
    for (stream,piece),g in d.groupby(["stream_id","piece"],sort=False):
        g=g.sort_values("time_s",kind="stable").copy()
        values=g[outcome].where(g.valid_rate_interval)
        if detector["mode"]=="relative":
            indexed=pd.Series(values.to_numpy(),index=pd.to_timedelta(g.time_s,unit="s"))
            baseline=indexed.where(indexed.gt(1)).rolling(str(detector["baseline_s"])+"s",
                closed="left",min_periods=detector["min_history_reports"]).median().to_numpy()
            mask=values.lt(baseline*(1-detector["drop_fraction"])) & (baseline>1)
            g["baseline_kbps"]=baseline;symptom="throughput_dip"
        elif detector["mode"]=="absolute":
            threshold=detector["absolute_threshold"]
            mask=values.lt(threshold) if outcome=="throughput_kbps" else values.gt(threshold)
            symptom="absolute_threshold_exceedance";g["baseline_kbps"]=np.nan
        else:
            mask=values.gt(0);symptom="timeout_run";g["baseline_kbps"]=np.nan
        g["target_event"]=mask.fillna(False)
        annotated.append(g)
        m=g.target_event.to_numpy(bool)
        starts=np.flatnonzero(m&~np.r_[False,m[:-1]])
        ends=np.flatnonzero(m&~np.r_[m[1:],False])
        for begin,end in zip(starts,ends):
            q=g.iloc[begin:end+1];duration=float(q.loc[q.valid_rate_interval,"dt"].sum())
            if duration+1e-9<detector["min_duration_s"]:continue
            identity=(stream,int(piece),outcome,symptom,tuple(q.source_row.astype(int)))
            row={"event_id":"ev2_"+hashlib.sha256(repr(identity).encode()).hexdigest()[:12],
                 "kind":"target_event","symptom":symptom,"stream_id":stream,"piece":int(piece),
                 "start_s":float(max(0,q.time_s.iloc[0]-q.dt.iloc[0])),"end_s":float(q.time_s.iloc[-1]),
                 "observed_duration_s":duration,"source_row_first":int(q.source_row.min()),
                 "source_row_last":int(q.source_row.max()),"source_rows":list(q.source_row.astype(int)),
                 "source_file":q.source_file.iloc[0],"primary_outcome":outcome,
                 "timeout_present":bool(q.stall_flag.gt(0).any()) if "stall_flag" in q else False,
                 "outcome_interval_weighted":_weighted(q,outcome),"causal_level":"E0_symptom",
                 "load_status":"no_tx_load_unresolved" if "tx_total" in q and q.tx_total.notna().all() and q.tx_total.eq(0).all() else "demand_unresolved"}
            for c in ["dataset","condition","segment","hdl"]:row[c]=q[c].iloc[0]
            events.append(row)
    cols=["event_id","kind","stream_id","piece","start_s","end_s","observed_duration_s","dataset","condition","segment","hdl"]
    return pd.DataFrame(events) if events else pd.DataFrame(columns=cols),pd.concat(annotated,ignore_index=True)

def process_context(g,q,event,contract,adapter):
    """Describe adaptive transitions without pretending the entire event is matched."""
    start=float(event["start_s"]);piece=g[g.piece.eq(event["piece"])]
    pre_start=max(float(piece.time_s.min()),start-2.0)
    prior=piece[(piece.time_s-piece.dt>=pre_start-1e-8)&piece.time_s.le(start+1e-8)]
    span=start-pre_start
    known=prior.valid_rate_interval&prior[contract["primary_outcome"]].notna()
    if span>0 and prior.loc[known,"dt"].sum()/span>=.8:
        prelude={"status":"available_unmatched_process_context","start_s":pre_start,"end_s":start,
                 "interpretation":"unfiltered_pre_event_trajectory_not_clean_or_matched_reference",
                 "prior_primary_alarm_reports":int(prior.target_event.sum()) if "target_event" in prior else None,
                 "last_prior_report_already_alarm":bool(prior.target_event.iloc[-1]) if "target_event" in prior and len(prior) else None,
                 **window_summary(prior,adapter)}
    else:prelude={"status":"unavailable","reason":"insufficient_continuous_prelude"}
    fields=[x for x in adapter.get("diagnostic_roles",{}).get("control",[]) if x in q]
    changed=pd.Series(False,index=q.index)
    for field in fields:
        changed|=q[field].ne(q[field].shift()) & ~(q[field].isna()&q[field].shift().isna())
    if len(changed):changed.iloc[0]=True
    phases=[]
    for idx,z in q.groupby(changed.cumsum(),sort=False):
        begin=float(max(0,z.time_s.iloc[0]-z.dt.iloc[0]));end=float(z.time_s.iloc[-1])
        summary=window_summary(z,adapter);duration=summary["valid_seconds"]
        if duration>=contract["detector"]["min_duration_s"]:
            e={"piece":int(event["piece"]),"start_s":begin}
            ref,_=select_reference(g,z,e,contract,adapter)
        else:ref={"status":"unavailable","reason":"phase_too_short_for_reference"}
        phases.append({"phase":int(idx),"start_s":begin,"end_s":end,"observed_seconds":duration,
                       "settings":summary["settings"],"event":summary,"reference":ref,
                       "metrics":compare_metrics(summary,ref,adapter)})
    return prelude,phases

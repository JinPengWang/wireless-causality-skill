"""Gated causal estimation for externally randomized paired switchback blocks.
No inference of treatment labels from outcomes or from an assumed 30 s period.
"""
import itertools
import numpy as np
import pandas as pd

REQUIRED_ATTESTATIONS=[
 "independent_treatment_log","randomized_pair_order","randomization_record_verified",
 "consistency_reviewed","no_carryover_after_washout","no_unmodeled_interference_between_units",
 "session_clock_alignment_verified","no_treatment_dependent_missingness_reviewed",
 "outcome_definition_verified"]
def causal_gate(design=None):
    if not design:
        return {"status":"not_identified","evidence_level":"E1_maximum",
          "causal_effect":None,"missing":REQUIRED_ATTESTATIONS,
          "reason":"缺少独立处理日志及识别设计；不能由卡顿/吞吐量/干扰指标反推处理标签"}
    missing=[x for x in REQUIRED_ATTESTATIONS if design.get(x) is not True]
    for key in ["estimand","treatment_definition","outcome","randomization_protocol","population"]:
        if not isinstance(design.get(key),str) or not design[key].strip():missing.append(key)
    if design.get("design")!="randomized_paired_switchback":missing.append("supported_design")
    washout=design.get("washout_s")
    if not isinstance(washout,(int,float)) or not np.isfinite(washout) or washout<0:missing.append("washout_s")
    if missing:return {"status":"not_identified","evidence_level":"E1_maximum","causal_effect":None,"missing":missing}
    return {"status":"design_attested_requires_data_checks","evidence_level":"E2_conditional",
      "warning":"识别假设来自设计记录和专家核验，代码无法从观测数据证明这些假设"}

def estimate_switchback(d,blocks,design,seed=20261023):
    gate=causal_gate(design)
    if gate["status"]!="design_attested_requires_data_checks":return gate,pd.DataFrame()
    needed=["session_id","block_id","pair_id","start_s","end_s","treatment","assignment_source"]
    absent=[x for x in needed if x not in blocks]
    if absent: raise ValueError("Missing treatment log columns: "+str(absent))
    if blocks[needed].isna().any().any():raise ValueError("Null treatment log cells")
    if not blocks.treatment.isin([0,1]).all():raise ValueError("Treatment must be 0 or 1")
    if blocks.duplicated(["session_id","block_id"]).any():raise ValueError("Duplicate treatment block")
    if not blocks.assignment_source.astype(str).str.strip().ne("").all():raise ValueError("Independent source required")
    if blocks.assignment_source.astype(str).str.contains("inferred|outcome|tx_flushed|throughput",case=False,regex=True).any():
        raise ValueError("Treatment source appears outcome-derived; independent log required")
    if not set(blocks.session_id).issubset(set(d.session_id)):raise ValueError("Treatment log has unknown sessions")
    outcome=design["outcome"]
    if outcome not in d:raise ValueError("Outcome missing: "+outcome)
    b=blocks.copy().sort_values(["session_id","start_s"])
    if not (b.end_s>b.start_s).all():raise ValueError("Invalid treatment intervals")
    for _,q in b.groupby("session_id"):
        if (q.start_s.to_numpy()[1:]<q.end_s.to_numpy()[:-1]).any():raise ValueError("Overlapping treatment intervals")
    for _,q in b.groupby(["session_id","pair_id"]):
        if len(q)!=2 or set(q.treatment)!={0,1}:raise ValueError("Each pair needs one control and one treated block")
    estimates=[]
    for _,row in b.iterrows():
        start=float(row.start_s)+design["washout_s"];end=float(row.end_s)
        if end-start<5:raise ValueError("At least 5 seconds usable duration per block required")
        session=d[d.session_id.eq(row.session_id)]
        streams=[]
        for stream,q in session.groupby("stream_id"):
            clock=q["session_time_s"] if "session_time_s" in q else q.time_s
            if clock.isna().any():
                offsets=design.get("stream_clock_offsets_s",{})
                if stream not in offsets or not np.isfinite(offsets[stream]):
                    raise ValueError("Truncated clocks need verified per-stream offsets: "+stream)
                clock=q.time_s+float(offsets[stream])
            valid=(clock-q.dt>=start)&clock.le(end)&q.valid_rate_interval&q[outcome].notna()
            w=q.loc[valid,"dt"]
            coverage=float(w.sum()/(end-start))
            if coverage<design.get("min_coverage",.8):raise ValueError("Insufficient treatment block coverage: "+str(row.block_id))
            streams.append(float(np.average(q.loc[valid,outcome],weights=w)))
        if not streams:raise ValueError("No outcomes in treatment block")
        estimates.append({**row.to_dict(),"block_outcome":float(np.mean(streams)),"n_links":len(streams)})
    e=pd.DataFrame(estimates)
    paired=e.pivot(index=["session_id","pair_id"],columns="treatment",values="block_outcome")
    paired["difference"]=paired[1]-paired[0]
    # Shared links and repeated toggles are not treated as independent devices/experiments.
    session_effects=paired["difference"].groupby("session_id").mean()
    n=len(session_effects)
    result={"status":"estimated_conditional_on_design","evidence_level":"E2_conditional",
      "estimand":design["estimand"],"outcome":outcome,"treatment_definition":design["treatment_definition"],
      "unit":"session","n_independent_sessions_assumed":n,"n_pairs":len(paired),
      "estimate":float(session_effects.mean()),"weighting":"equal session means of paired block differences",
      "assumptions":{x:design[x] for x in REQUIRED_ATTESTATIONS},
      "causal_caveat":"只有设计和独立性假设成立时才解释为该试验样本/条件的平均因果效应；不是自动发现全部根因"}
    if n<8:
        result.update({"interval_status":"fewer_than_8_independent_sessions","ci95":None,"p_signflip":None})
    else:
        v=session_effects.to_numpy();rng=np.random.default_rng(seed)
        boot=v[rng.integers(0,n,size=(4000,n))].mean(1)
        result["ci95"]=np.quantile(boot,[.025,.975]).tolist()
        if n<=16:
            null=np.array([np.mean(v*np.array(sign)) for sign in itertools.product([-1,1],repeat=n)])
            p=float(np.mean(np.abs(null)>=abs(v.mean())-1e-12))
        else:
            null=(rng.choice([-1,1],size=(9999,n))*v).mean(1)
            p=float((1+np.sum(np.abs(null)>=abs(v.mean())))/10000)
        result["p_signflip"]=p
        result["signflip_assumption"]="whole-session joint treatment-label swaps allowed by randomization design"
        result["leave_one_session_out_range"]=[float(np.min((v.sum()-v)/(n-1))),float(np.max((v.sum()-v)/(n-1)))]
    return result,e

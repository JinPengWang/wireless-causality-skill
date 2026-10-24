"""Explicit reference-device contrasts over shared acquisition strata."""
import numpy as np
import pandas as pd

def compare_cohort(d,contract,adapter,seed=20261023):
    config=contract["comparison"];required=config["match_fields"];metrics=config["metrics"]
    if d.device_id.isna().any():
        return {"status":"blocked","reason":"设备身份映射缺失；hdl不能替代设备","unmapped_reports":int(d.device_id.isna().sum())},pd.DataFrame()
    devices=sorted(d.device_id.astype(str).unique())
    if len(devices)<2:return {"status":"blocked","reason":"至少需要两个有身份的设备实例"},pd.DataFrame()
    ref=config["reference_device"]
    if ref is None:
        if len(devices)==2:ref=devices[0]
        else:return {"status":"blocked","reason":"多设备比较必须明确reference_device，不自动选冠军作为对照","available_devices":devices},pd.DataFrame()
    if ref not in devices:raise ValueError("Reference device is not in the investigation population")
    targets=config["target_devices"] or [x for x in devices if x!=ref]
    if ref in targets or len(set(targets))!=len(targets) or set(targets)-set(devices):raise ValueError("Invalid target_devices")
    missing=[c for c in required+metrics if c not in d]
    if missing:return {"status":"blocked","reason":"缺少匹配或结果字段","missing":missing},pd.DataFrame()
    if not required or "pair_id" not in required:return {"status":"blocked","reason":"必须明确采集配对编号及共同条件"},pd.DataFrame()
    if d[required].isna().any().any():return {"status":"blocked","reason":"匹配条件有未知值，不静默补齐或删行"},pd.DataFrame()
    multi=d.groupby("device_id").hdl.nunique().gt(1).any()
    if multi and "link_role" not in required:
        return {"status":"blocked","reason":"每设备有多条链路，先指定共同link_role或缩小到单链路，避免角色混合"},pd.DataFrame()
    roles=adapter.get("diagnostic_roles",{})
    explanatory=list(dict.fromkeys(sum(roles.values(),[])+["ack_ratio","delay_proxy_ms"]))
    cell_rows=[]
    for key,g in d.groupby(required,dropna=False,sort=False):
        key=key if isinstance(key,tuple) else (key,)
        for dev,q in g.groupby("device_id",sort=False):
            row=dict(zip(required,key));row["device_id"]=str(dev);row["reports"]=len(q)
            row["source_refs"]=[{"file":str(f),"row_first":int(z.source_row.min()),"row_last":int(z.source_row.max()),
                               "stream_id":str(stream)} for (f,stream),z in q.groupby(["source_file","stream_id"],sort=False)]
            for metric in list(dict.fromkeys(metrics+explanatory)):
                if metric not in q:row[metric]=np.nan;continue
                valid=q.valid_rate_interval&q[metric].notna()
                if not valid.any():row[metric]=np.nan
                elif metric in adapter.get("diagnostic_roles",{}).get("scheduler",[]) or metric in {"retry_count","failure_count"}:
                    row[metric]=float(q.loc[valid,metric].sum()/q.loc[valid,"dt"].sum())
                elif metric=="ack_ratio" and "tx_ack" in q:
                    ok=valid&q.tx_total.gt(0)&q.tx_ack.between(0,q.tx_total)
                    row[metric]=float(q.loc[ok,"tx_ack"].sum()/q.loc[ok,"tx_total"].sum()) if ok.any() else np.nan
                elif metric=="delay_proxy_ms" and "cnt_diff_total" in q:
                    ok=valid&q.cnt_total_nb.gt(0)&q.cnt_diff_total.notna()
                    row[metric]=float(adapter["counter_period_ms"]*q.loc[ok,"cnt_diff_total"].sum()/q.loc[ok,"cnt_total_nb"].sum()) if ok.any() else np.nan
                else:row[metric]=float(q.loc[valid,metric].iloc[0]) if q.loc[valid,metric].nunique()==1 else float(np.average(q.loc[valid,metric],weights=q.loc[valid,"dt"]))
            cell_rows.append(row)
    cells=pd.DataFrame(cell_rows);matched=[];summaries=[];mechanisms=[]
    for target in targets:
        a=cells[cells.device_id.eq(ref)].set_index(required)
        b=cells[cells.device_id.eq(target)].set_index(required)
        common=a.index.intersection(b.index,sort=False)
        pair_rows=[]
        for key in common:
            ar=a.loc[key];br=b.loc[key]
            kv=key if isinstance(key,tuple) else (key,)
            base=dict(zip(required,kv))
            for feature in explanatory:
                if not np.isfinite(ar[feature]) or not np.isfinite(br[feature]):continue
                family=next((role for role,names in roles.items() if feature in names),"reliability_proxy")
                mechanisms.append({**base,"reference_device":ref,"target_device":target,
                  "feature":feature,"role":family,"reference_value":float(ar[feature]),"target_value":float(br[feature]),
                  "target_minus_reference":float(br[feature]-ar[feature]),
                  "evidence_level":"E1_descriptive","interpretation":"paired_working_point_difference_not_causal_attribution",
                  "reference_source_refs":ar["source_refs"],"target_source_refs":br["source_refs"]})
            for metric in metrics:
                if not np.isfinite(ar[metric]) or not np.isfinite(br[metric]):continue
                row={**base,"reference_device":ref,"target_device":target,"metric":metric,
                     "reference_value":float(ar[metric]),"target_value":float(br[metric]),
                     "target_minus_reference":float(br[metric]-ar[metric]),
                     "reference_source_refs":ar["source_refs"],"target_source_refs":br["source_refs"]}
                pair_rows.append(row);matched.append(row)
        summary={"reference_device":ref,"target_device":target,
                 "reference_strata":len(a),"target_strata":len(b),"common_strata":len(common),
                 "reference_common_fraction":len(common)/len(a) if len(a) else 0,
                 "target_common_fraction":len(common)/len(b) if len(b) else 0,
                 "unmatched_reference_strata":len(a)-len(common),"unmatched_target_strata":len(b)-len(common),
                 "unmatched_conditions":[{"present_in":dev,"conditions":dict(zip(required,key if isinstance(key,tuple) else (key,)))}
                   for dev,keys in [(ref,a.index.difference(common)),(target,b.index.difference(common))] for key in keys],
                 "contrasts":[]}
        for metric in metrics:
            q=pd.DataFrame([x for x in pair_rows if x["metric"]==metric])
            if q.empty:
                summary["contrasts"].append({"metric":metric,"status":"no_measured_common_support"});continue
            v=q.groupby("pair_id").target_minus_reference.mean().to_numpy()
            result={"metric":metric,"status":"descriptive_matched_contrast","acquisition_pairs":len(v),
                    "mean_target_minus_reference":float(v.mean()),"evidence_level":"E1",
                    "inference":"conditional_on_these_physical_devices_and_matching_conditions"}
            if len(v)>=8:
                rng=np.random.default_rng(seed)
                boot=v[rng.integers(0,len(v),(2000,len(v)))].mean(1)
                result["conditional_pair_bootstrap_ci95"]=np.quantile(boot,[.025,.975]).tolist()
            else:result["interval_status"]="fewer_than_8_acquisition_pairs"
            summary["contrasts"].append(result)
        summaries.append(summary)
    return {"status":"descriptive_reference_cohort" if matched else "blocked_no_common_measured_support","reference_device":ref,"comparisons":summaries,
      "mechanism_observations":mechanisms,
      "comparison_family":{"targets":len(targets),"metrics":len(metrics),
          "ci_interpretation":"marginal_descriptive_intervals_not_simultaneous_rank_or_significance_claims"},
      "limitation":"共同条件仍可能遗漏环境/负载混杂；采集配对不是同型号多台设备的独立复制，不生成因果设备排名"},pd.DataFrame(matched)

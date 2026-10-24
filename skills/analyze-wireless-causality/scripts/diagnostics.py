"""Event localization, within-stream association screens and matched contrasts."""
import hashlib
import numpy as np
import pandas as pd
from scipy.stats import rankdata

def stable_seed(key, seed=20261023):
    return int(hashlib.sha256((str(seed)+str(key)).encode()).hexdigest()[:8],16)

def bh_adjust(p):
    p=np.asarray(p,float);out=np.full(len(p),np.nan); valid=np.isfinite(p)
    a=p[valid];order=np.argsort(a); n=len(a)
    if n:
        q=np.minimum.accumulate((a[order]*n/np.arange(1,n+1))[::-1])[::-1]
        r=np.empty(n);r[order]=np.minimum(q,1);out[valid]=r
    return out

def summarize(d):
    rows=[]
    for keys,g in d.groupby(["dataset","condition","segment","hdl","device_id"],sort=False,dropna=False):
        valid=g.valid_rate_interval & g.throughput_kbps.notna()
        elapsed=g.loc[valid,"dt"].sum()
        row=dict(zip(["dataset","condition","segment","hdl","device_id"],keys))
        row.update({"reports":len(g),"span_s":g.time_s.max()-g.time_s.min(),
          "valid_rate_s":float(elapsed),"valid_rate_reports":int(valid.sum()),
          "throughput_kbps":float(np.average(g.loc[valid,"throughput_kbps"],weights=g.loc[valid,"dt"])) if elapsed>0 else np.nan,
          "throughput_p10_kbps":g.loc[valid,"throughput_kbps"].quantile(.1),
          "rssi_median":g.rssi_valid.median() if "rssi_valid" in g and g.rssi_valid.notna().any() else np.nan})
        if "tx_flushed" in g:
            ok=g.tx_total.gt(0)&g.tx_ack.between(0,g.tx_total)
            row.update({"flush_positive_reports":int(g.tx_flushed.gt(0).sum()),
                "flush_report_fraction":g.tx_flushed.gt(0).mean(),"flushed_count":g.tx_flushed.sum(),
                "ack_ratio":g.loc[ok,"tx_ack"].sum()/g.loc[ok,"tx_total"].sum() if ok.any() else np.nan,
                "delay_proxy_ms":20*g.cnt_diff_total.sum()/g.loc[g.cnt_diff_total.notna(),"cnt_total_nb"].sum()
                    if g.loc[g.cnt_diff_total.notna(),"cnt_total_nb"].sum()>0 else np.nan})
        rows.append(row)
    return pd.DataFrame(rows)

def detect_events(d, drop_fraction=.5, min_duration=.3, baseline_s=10.0):
    events=[]; annotations=[]
    for (stream,piece),g in d.groupby(["stream_id","piece"],sort=False):
        g=g.copy()
        indexed=pd.Series(g.throughput_kbps.to_numpy(), index=pd.to_timedelta(g.time_s,unit="s"))
        # Past observations only. A zero/no-demand period does not calibrate capacity.
        baseline=indexed.where(indexed.gt(1)).rolling(str(baseline_s)+"s",closed="left",min_periods=30).median()
        g["baseline_kbps"]=baseline.to_numpy()
        g["dip"]=g.throughput_kbps.lt(g.baseline_kbps*(1-drop_fraction)) & g.baseline_kbps.gt(1)
        annotations.append(g)
        kinds={"throughput_dip":g.dip.to_numpy()}
        if "stall_flag" in g: kinds["flush_run"]=g.stall_flag.eq(1).to_numpy()
        for kind,mask in kinds.items():
            starts=np.flatnonzero(mask & ~np.r_[False,mask[:-1]])
            ends=np.flatnonzero(mask & ~np.r_[mask[1:],False])
            for start,end in zip(starts,ends):
                q=g.iloc[start:end+1]
                duration=float(q.dt.where(q.valid_rate_interval,0).sum())
                if duration<min_duration: continue
                before=g.iloc[max(0,start-20):start]
                no_tx=bool("tx_total" in q and q.tx_total.sum()==0)
                row={"event_id":"ev_"+hashlib.sha256((stream+str(piece)+kind+str(start)).encode()).hexdigest()[:12],
                  "kind":kind,"stream_id":stream,"dataset":q.dataset.iloc[0],
                  "condition":q.condition.iloc[0],"segment":q.segment.iloc[0],"hdl":q.hdl.iloc[0],
                  "piece":int(piece),"start_s":float(max(0,q.time_s.iloc[0]-q.dt.iloc[0])),
                  "end_s":float(q.time_s.iloc[-1]),"observed_duration_s":duration,
                  "source_file":q.source_file.iloc[0],"source_row_first":int(q.source_row.iloc[0]),
                  "source_row_last":int(q.source_row.iloc[-1]),
                  "baseline_kbps":float(q.baseline_kbps.median()),
                  "throughput_kbps":float(q.throughput_kbps.mean()),
                  "minimum_kbps":float(q.throughput_kbps.min()),
                  "load_status":"no_tx_load_unresolved" if no_tx else "offered_load_unmeasured",
                  "causal_level":"E0_event_only"}
                for col in ["interf_avg","weighted_interf_avg","rssi_valid","bitrate","pwrlev","ack_ratio","delay_proxy_ms","stall_flag"]:
                    if col in q:
                        row[col+"_during"]=q[col].mean()
                        row[col+"_before"]=before[col].mean()
                events.append(row)
    cols=["event_id","kind","stream_id","dataset","condition","segment","hdl","piece","start_s","end_s",
      "observed_duration_s","source_file","source_row_first","source_row_last","baseline_kbps","throughput_kbps"]
    return pd.DataFrame(events) if events else pd.DataFrame(columns=cols),pd.concat(annotations,ignore_index=True)

def _corr(x,y):
    x=np.asarray(x,float);y=np.asarray(y,float);x=x-x.mean();y=y-y.mean()
    den=np.sqrt(np.dot(x,x)*np.dot(y,y))
    return float(np.dot(x,y)/den) if den>1e-12 else np.nan

def lag_screen(blocks, candidates, outcomes, seed=20261023, lags=(-1,0,1,2,5),min_blocks=60):
    """Stationarity-dependent exploratory cyclic-shift diagnostics, not causal identification.
    Positive lag means X earlier than Y. Missing/low-coverage windows split runs.
    One global BH family includes all outcomes, features, lags, streams and runs."""
    rows=[]
    for (stream,piece),g in blocks.groupby(["stream_id","piece"],sort=False):
        g=g.sort_values("block").copy()
        for feature in candidates:
            for outcome in outcomes:
                if feature not in g or outcome not in g: continue
                good=g.eligible & g[feature].notna() & g[outcome].notna()
                run=((g.block.diff()!=1)|~good|~good.shift(fill_value=False)).cumsum()
                for run_id,q in g[good].groupby(run[good]):
                    if len(q)<min_blocks: continue
                    x=q[feature].to_numpy(float);y=q[outcome].to_numpy(float)
                    # Aggregation roundoff must not manufacture ranked variation from constants.
                    if np.allclose(x,x[0],rtol=1e-12,atol=1e-12) or np.allclose(y,y[0],rtol=1e-12,atol=1e-12):continue
                    for lag in lags:
                        if lag>0: xx,yy=x[:-lag],y[lag:]
                        elif lag<0: xx,yy=x[-lag:],y[:lag]
                        else: xx,yy=x,y
                        xr,yr=rankdata(xx),rankdata(yy);rho=_corr(xr,yr)
                        if not np.isfinite(rho): continue
                        n=len(xr); shifts=np.arange(10,n-9)
                        if len(shifts)>499:
                            rng=np.random.default_rng(stable_seed((stream,piece,run_id,feature,outcome,lag),seed))
                            shifts=rng.choice(shifts,499,replace=False)
                        null=np.array([_corr(np.roll(xr,int(k)),yr) for k in shifts])
                        p=(1+int(np.sum(np.abs(null)>=abs(rho))))/(1+len(null))
                        # Remove linear drift as a sensitivity contrast; not a confounder-adjusted effect.
                        t=np.linspace(-1,1,n);z=np.column_stack([np.ones(n),t])
                        rx=xr-z@np.linalg.lstsq(z,xr,rcond=None)[0]
                        ry=yr-z@np.linalg.lstsq(z,yr,rcond=None)[0]
                        rows.append({"stream_id":stream,"dataset":q.dataset.iloc[0],
                            "condition":q.condition.iloc[0],"segment":q.segment.iloc[0],"hdl":q.hdl.iloc[0],
                            "piece":int(piece),"run":int(run_id),"feature":feature,"outcome":outcome,
                            "lag_s":lag,"n_blocks":n,"spearman_rho":rho,"detrended_rho":_corr(rx,ry),
                            "p_shift_exploratory":p,"null_shifts":len(shifts),
                            "time_relation":"future_feature_placebo" if lag<0 else "same_bin" if lag==0 else "past_feature",
                            "evidence_level":"E1_association","causal_identified":False})
    cols=["feature","outcome","lag_s","spearman_rho","p_shift_exploratory","q_shift_exploratory"]
    if not rows:return pd.DataFrame(columns=cols)
    result=pd.DataFrame(rows)
    result["q_shift_exploratory"]=bh_adjust(result.p_shift_exploratory)
    return result.sort_values(["q_shift_exploratory","p_shift_exploratory"]).reset_index(drop=True)

def compare_devices(d, adapter, metric="throughput_kbps", seed=20261023):
    required=adapter.get("matched_covariates",["condition","pair_id"])
    missing=[c for c in required if c not in d]
    if d.device_id.isna().all():
        return {"status":"blocked","reason":"只有链路hdl，没有物理设备/型号/固件身份；禁止将h5与h6命名为设备A/B"},pd.DataFrame()
    if missing:return {"status":"blocked","reason":"缺少匹配条件","missing":missing},pd.DataFrame()
    if len(d.device_id.unique())!=2:
        return {"status":"blocked","reason":"本版本配对比较器需要恰好两组device_id；多设备按预先指定对照逐对比较并校正"},pd.DataFrame()
    if d[required].isna().any().any():
        return {"status":"blocked","reason":"匹配字段有缺失，未擅自删行或补齐"},pd.DataFrame()
    devs=sorted(d.device_id.unique()); rows=[]
    for key,g in d.groupby(required,dropna=False,sort=False):
        vals={}
        for dev,q in g.groupby("device_id"):
            v=q.valid_rate_interval & q[metric].notna()
            if v.any(): vals[dev]=float(np.average(q.loc[v,metric],weights=q.loc[v,"dt"]))
        if all(v in vals for v in devs):
            row=dict(zip(required,key if isinstance(key,tuple) else (key,)))
            row.update({"device_a":devs[0],"device_b":devs[1],"a":vals[devs[0]],"b":vals[devs[1]],"b_minus_a":vals[devs[1]]-vals[devs[0]]})
            rows.append(row)
    pairs=pd.DataFrame(rows)
    if not len(pairs):return {"status":"blocked","reason":"没有共同条件配对，无法形成可比样本"},pairs
    # Resample acquisition pair_id, preserving all strata from each repeat together.
    per_repeat=pairs.groupby("pair_id").b_minus_a.mean()
    result={"status":"descriptive_matched_contrast","metric":metric,"devices":devs,
        "matched_strata":len(pairs),"acquisition_pairs":len(per_repeat),"mean_b_minus_a":per_repeat.mean(),
        "unmatched_strata":d.groupby(required).ngroups-len(pairs),
        "evidence_level":"E1","limitation":"同一物理设备重复采集不能替代多台同型号设备；非随机化时差异不是设备因果效应"}
    if len(per_repeat)>=5:
        rng=np.random.default_rng(seed);v=per_repeat.to_numpy()
        boot=v[rng.integers(0,len(v),(2000,len(v)))].mean(1)
        result["conditional_pair_bootstrap_95ci"]=np.quantile(boot,[.025,.975]).tolist()
    else: result["interval_status"]="少于5个采集配对，不报告可推广置信区间"
    return result,pairs

"""Protocol adapters and provenance-preserving data preparation. Python >=3.9."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

KEY = ["dataset", "condition", "segment", "hdl"]

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def write_json(path, value):
    def clean(x):
        if isinstance(x, dict): return {str(k): clean(v) for k,v in x.items()}
        if isinstance(x, (list,tuple)): return [clean(v) for v in x]
        if isinstance(x, np.ndarray): return clean(x.tolist())
        if isinstance(x, np.generic): return clean(x.item())
        if isinstance(x, float) and not np.isfinite(x): return None
        if isinstance(x, Path): return str(x)
        return x
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()

def inventory(paths, root):
    result=[]
    for p in sorted(set(map(Path,paths))):
        result.append({"path":str(p.relative_to(root)) if p.is_relative_to(root) else str(p),
                       "size_bytes":p.stat().st_size,"sha256":sha256(p)})
    return result

def _relative_time(g):
    """Use precise full timestamps, else retain order and sum real per-link dt.
    Truncated mm:ss.s strings are not parsed as dates. No invented absolute time."""
    text=g["time"].astype(str)
    full=text.str.match(r"^\d{4}-\d{2}-\d{2}[ T]").all()
    if full:
        ts=pd.to_datetime(text, errors="coerce", format="mixed")
        if ts.isna().any(): raise ValueError("Invalid full timestamp")
        t=(ts-ts.iloc[0]).dt.total_seconds()
        if (t.diff().dropna()<0).any(): raise ValueError("Nonmonotone source timestamps")
        return t.to_numpy(), "source_full_timestamp"
    dt=pd.to_numeric(g["dt"], errors="coerce").to_numpy(float)
    if np.any(~np.isfinite(dt[1:])) or np.any(dt[1:]<0):
        raise ValueError("Truncated time requires nonnegative finite dt after first report")
    dt[0]=0
    return np.cumsum(dt), "relative_reconstructed_from_dt"

def _derive(g, adapter):
    g=g.copy()
    dt=pd.to_numeric(g["dt"],errors="coerce")
    cfg=adapter["interval"]
    g["valid_rate_interval"]=dt.ge(cfg["min_rate_s"]) & dt.le(cfg["gap_s"])
    g["throughput_kbps"]=8*g["total_tx_size"]/(1000*dt.where(g.valid_rate_interval))
    g["stall_flag"]=g.tx_flushed.gt(0).astype(float).where(g.tx_flushed.notna())
    valid_ack=g.tx_total.gt(0)&g.tx_ack.ge(0)&g.tx_ack.le(g.tx_total)
    g["ack_ratio"]=g.tx_ack.div(g.tx_total).where(valid_ack)
    g["rssi_valid"]=g.rssi_avg.where(g.rssi_avg.lt(0))
    g["delay_proxy_ms"]=adapter["counter_period_ms"]*g.cnt_diff_total.div(g.cnt_total_nb.where(g.cnt_total_nb.gt(0)))
    g["time_s"],method=_relative_time(g)
    g["time_method"]=method
    # Never form events or lags across discontinuity, nonpositive interval or missing dt.
    jump=pd.Series(g.time_s.to_numpy()).diff().to_numpy()
    cuts=(dt.to_numpy()<=0)|~np.isfinite(dt.to_numpy())|(jump>cfg["gap_s"])
    cuts[0]=True
    g["piece"]=np.cumsum(cuts)-1
    return g

def load_sle(root, adapter):
    frames=[]; audit=[]; paths=[]; npz_rows=[]; channel_rows=[]
    for folder in adapter["dataset_dirs"]:
        fp=Path(root)/folder
        d=pd.read_csv(fp/"base.csv")
        meta=read_json(fp/"base.json")
        paths.extend(p for p in fp.iterdir() if p.suffix in [".csv",".json",".npz"])
        if list(d.columns)!=meta["columns"]: raise ValueError("base.csv schema differs from base.json: "+folder)
        if len(d)!=meta["totals"]["rows"]: raise ValueError("Source row count mismatch: "+folder)
        d["dataset"]=folder; d["source_file"]=folder+"/base.csv"
        d["source_row"]=np.arange(len(d))+2
        # Full duplicates are flagged, not silently removed; time duplicates can be legitimate.
        for key,g in d.groupby(KEY,sort=False,dropna=False):
            g=_derive(g,adapter)
            g["stream_id"]="|".join(map(str,key))
            g["session_id"]="|".join([adapter["protocol"],str(g.segment.iloc[0]),str(g.condition.iloc[0])])
            g["device_id"]=pd.NA
            frames.append(g)
        audit.append({"dataset":folder,"rows":len(d),"segments":d.segment.nunique(),
          "conditions":d.condition.nunique(),"dt_zero":int(d.dt.eq(0).sum()),
          "dt_missing":int(d.dt.isna().sum()),"dt_over_gap":int(d.dt.gt(adapter["interval"]["gap_s"]).sum()),
          "dt_max_s":d.dt.max(),"full_duplicate_rows":int(d.drop(columns=["source_row"]).duplicated().sum()),
          "rssi_zero":int(d.rssi_avg.eq(0).sum()),"flush_positive_reports":int(d.tx_flushed.gt(0).sum()),
          "flush_count":int(d.tx_flushed.sum()),"source_device_id":False,
          "source_intervention_log":False,"shortened_time_rows":int((~d.time.astype(str).str.match(r"^\d{4}-")).sum())})
        if (fp/"chan.csv").exists():
            c=pd.read_csv(fp/"chan.csv")
            expected=0; observed=0
            for _,q in c.groupby(["condition","segment"],sort=False):
                for link in ["h5","h6"]:
                    n=q["n_"+link]
                    expected+=len(q); observed+=int(n.gt(0).sum())
            channel_rows.append({"dataset":folder,"expected_link_bins":expected,"observed_link_bins":observed,
                "missing_link_bin_fraction":1-observed/expected,
                "report_count_conserved":bool(np.isclose(c.n.sum(),len(d))),
                "grid_contiguous":bool(c.groupby(["condition","segment"]).bin.diff().dropna().eq(1).all()),
                "episode_grid_hash_matches":sha256(fp/"chan.csv")==read_json(fp/"episodes.json").get("grid_sha256")})
        if (fp/"dynamics.npz").exists():
            with np.load(fp/"dynamics.npz",allow_pickle=False) as z:
                nm=z["numeric_observed"]; tm=z["target_observed"]
                npz_rows.append({"dataset":folder,"windows":len(z["numeric"]),
                  "numeric_observed_fraction":float(nm.mean()),"target_observed_fraction":float(tm.mean()),
                  "numeric_mask_shape_valid":nm.shape==z["numeric"].shape,
                  "target_mask_shape_valid":tm.shape==z["targets"].shape,
                  "uses_future_as_predictor":False,
                  "purpose":"audit_only_not_independent_samples"})
    for p in [Path(root)/"SLE参数对照表_0813.xlsx",Path(root)/"场景介绍.png"]:
        if p.exists(): paths.append(p)
    out=pd.concat(frames,ignore_index=True)
    out["session_time_s"]=np.nan
    for _,q in out.groupby("session_id",sort=False):
        if q.time_method.eq("source_full_timestamp").all():
            ts=pd.to_datetime(q.time,format="mixed",errors="coerce")
            out.loc[q.index,"session_time_s"]=(ts-ts.min()).dt.total_seconds()
    return out, pd.DataFrame(audit), pd.DataFrame(channel_rows), pd.DataFrame(npz_rows),paths

def load_mapped_csv(path,adapter):
    src=pd.read_csv(path); ident=adapter["identity"]
    mandatory=[ident[x] for x in ["timestamp","device","session","scenario","link"]]
    missing=[c for c in mandatory if c not in src]
    if missing: raise ValueError("Missing identity columns: "+str(missing))
    if src[mandatory].isna().any().any(): raise ValueError("Null device/session/scenario/time/link identity")
    d=src.copy()
    d["dataset"]=adapter["protocol"]; d["condition"]=src[ident["scenario"]].astype(str)
    d["segment"]=src[ident["session"]].astype(str); d["hdl"]=src[ident["link"]].astype(str)
    d["device_id"]=src[ident["device"]].astype(str)
    d["source_file"]=Path(path).name; d["source_row"]=np.arange(len(src))+2
    d["_timestamp"]=pd.to_datetime(src[ident["timestamp"]],errors="coerce",utc=True,format="mixed")
    if d._timestamp.isna().any(): raise ValueError("Invalid timestamp")
    if d.duplicated(["device_id","segment","condition","hdl","_timestamp"]).any():
        raise ValueError("Duplicate device/session/link timestamps require explicit aggregation")
    frames=[]
    for key,g in d.groupby(["device_id","segment","condition","hdl"],sort=False):
        g=g.sort_values("_timestamp").copy()
        g["dt"]=g._timestamp.diff().dt.total_seconds()
        g["time_s"]=(g._timestamp-g._timestamp.iloc[0]).dt.total_seconds()
        g["time_method"]="source_full_timestamp"
        g["valid_rate_interval"]=g.dt.between(adapter["interval"]["min_rate_s"],adapter["interval"]["gap_s"])
        g["stream_id"]="|".join(map(str,key));g["session_id"]="|".join([adapter["protocol"],str(g.segment.iloc[0]),str(g.condition.iloc[0])])
        g["piece"]=(g.dt.isna()|g.dt.le(0)|g.dt.gt(adapter["interval"]["gap_s"])).cumsum()-1
        g["counter_reset"]=False
        for dest,spec in adapter["metrics"].items():
            if spec["source"] not in g: g[dest]=np.nan;continue
            raw=pd.to_numeric(g[spec["source"]],errors="coerce")
            if spec["kind"].startswith("cumulative"):
                delta=raw.diff()
                g["counter_reset"]|=delta.lt(0)
                val=delta.where(delta.ge(0)&g.valid_rate_interval)
                if spec["kind"]=="cumulative_bytes": val=val*spec.get("scale",.008)/g.dt
                else:val=val*spec.get("scale",1)
            elif spec["kind"] in ["interval_bytes","interval_count"]:
                val=raw.where(raw.ge(0)&g.valid_rate_interval)*spec.get("scale",.008 if spec["kind"]=="interval_bytes" else 1)
                if spec["kind"]=="interval_bytes":val=val/g.dt
            elif spec["kind"]=="gauge": val=raw*spec.get("scale",1)
            else:raise ValueError("Unknown metric kind: "+str(spec["kind"]))
            g[dest]=val
        g["piece"]=(g.piece.diff().fillna(1).ne(0)|g.counter_reset).cumsum()-1
        # Wi-Fi failures are not silently recoded to SLE stall events.
        frames.append(g)
    out=pd.concat(frames,ignore_index=True)
    session_origin=out.groupby("session_id")["_timestamp"].transform("min")
    out["session_time_s"]=(out._timestamp-session_origin).dt.total_seconds()
    if "throughput_kbps" not in out:out["throughput_kbps"]=np.nan
    if not any(name in out and out[name].notna().any() for name in adapter["metrics"]):
        raise ValueError("No valid metric observations; verify adapter mapping and timestamps")
    audit=pd.DataFrame([{"dataset":adapter["protocol"],"rows":len(out),
      "segments":out.segment.nunique(),"conditions":out.condition.nunique(),
      "dt_zero":int(out.dt.eq(0).sum()),"dt_missing":int(out.dt.isna().sum()),
      "dt_over_gap":int(out.dt.gt(adapter["interval"]["gap_s"]).sum()),
      "dt_max_s":out.dt.max(),"counter_resets":int(out.counter_reset.sum()),
      "source_device_id":True,"source_intervention_log":False}])
    return out,audit,pd.DataFrame(),pd.DataFrame(),[Path(path)]

def aggregate_blocks(d, seconds=1.0, min_coverage=.8, extra_metrics=None, count_metrics=None):
    """Disjoint fixed windows within stream and continuous piece; retain missing windows."""
    rows=[]
    for (stream,piece),g in d.groupby(["stream_id","piece"],sort=False):
        g=g.copy(); origin=g.time_s.iloc[0]
        # An interval belongs to its endpoint; boundary intervals are never split/invented.
        g["_block"]=np.floor((g.time_s-origin+1e-8)/seconds).astype(int)
        for k,q in g.groupby("_block",sort=False):
            good=q.valid_rate_interval
            seconds_observed=float(q.loc[good,"dt"].sum())
            row={"stream_id":stream,"session_id":q.session_id.iloc[0],"piece":int(piece),
              "block":int(k),"time_s":float(origin+k*seconds),"dataset":q.dataset.iloc[0],
              "condition":q.condition.iloc[0],"segment":q.segment.iloc[0],"hdl":q.hdl.iloc[0],
              "device_id":q.device_id.iloc[0],"coverage":min(seconds_observed/seconds,1.0),
              "observed_seconds":seconds_observed,"n_reports":len(q)}
            if (good & q.throughput_kbps.notna()).any():
                valid=good & q.throughput_kbps.notna()
                row["throughput_kbps"]=float(np.average(q.loc[valid,"throughput_kbps"],weights=q.loc[valid,"dt"]))
            else: row["throughput_kbps"]=np.nan
            metrics=["interf_avg","weighted_interf_avg","rssi_valid","bitrate","pwrlev",
              "abnormal_cnt","cancel_cnt","abort_cnt","delay_proxy_ms","channel_busy_pct",
              "phy_rate_mbps","retry_count","failure_count","latency_ms","stall_flag"]
            for col in list(dict.fromkeys(metrics+list(extra_metrics or []))):
                if col not in q:continue
                valid=good&q[col].notna()
                if not valid.any():row[col]=np.nan
                elif col in (count_metrics or []):row[col]=q.loc[valid,col].sum()/q.loc[valid,"dt"].sum()
                else:row[col]=float(q.loc[valid,col].iloc[0]) if q.loc[valid,col].nunique()==1 else float(np.average(q.loc[valid,col],weights=q.loc[valid,"dt"]))
            if "tx_ack" in q:
                ok=q.tx_total.gt(0)&q.tx_ack.between(0,q.tx_total)
                row["ack_ratio"]=q.loc[ok,"tx_ack"].sum()/q.loc[ok,"tx_total"].sum() if ok.any() else np.nan
            row["eligible"]=row["coverage"]>=min_coverage
            rows.append(row)
    return pd.DataFrame(rows)

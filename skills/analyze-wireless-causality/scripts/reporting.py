"""Offline scientific figures and a portable, self-contained HTML report."""
from pathlib import Path
import base64
import html
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

COLORS=["#156b8a","#df8c2c","#7159a6"]
def set_style():
    available={x.name for x in font_manager.fontManager.ttflist}
    fonts=[x for x in ["Microsoft YaHei","Noto Sans CJK SC","SimHei","DejaVu Sans"] if x in available]
    plt.rcParams.update({"font.family":fonts,"axes.unicode_minus":False,"font.size":10,
      "axes.spines.top":False,"axes.spines.right":False,"figure.facecolor":"white",
      "axes.grid":True,"grid.alpha":.18,"svg.fonttype":"none","savefig.dpi":170})

def savefig(fig,folder,name):
    folder.mkdir(parents=True,exist_ok=True)
    fig.savefig(folder/(name+".png"),bbox_inches="tight")
    fig.savefig(folder/(name+".svg"),bbox_inches="tight")
    plt.close(fig)
    return folder/(name+".png")

def make_figures(d,summary,events,blocks,screen,quality,out):
    set_style();out=Path(out);plots=[]
    datasets=list(d.dataset.unique())
    fig,axes=plt.subplots(1,3,figsize=(13.8,3.7))
    means=[];flush=[];coverage=[]
    for name in datasets:
        q=d[d.dataset.eq(name)];valid=q.valid_rate_interval&q.throughput_kbps.notna()
        means.append(np.average(q.loc[valid,"throughput_kbps"],weights=q.loc[valid,"dt"]) if valid.any() else np.nan)
        flush.append(100*q.stall_flag.mean() if "stall_flag" in q else len(q))
        coverage.append(100*valid.mean())
    labels=[x.replace("Before_0910_Mix","Mix").replace("0922_","") for x in datasets]
    for ax,values,title in zip(axes,[means,flush,coverage],["有效区间吞吐量 / kbps","超时放弃阳性上报 / %" if "stall_flag" in d else "原始上报条数","可计算吞吐量的上报 / %"]):
        ax.bar(labels,values,color=COLORS[:len(labels)],width=.58)
        ax.set_title(title)
        for i,v in enumerate(values):
            if np.isfinite(v):ax.text(i,v,f"{v:.2f}",ha="center",va="bottom")
        ax.margins(y=.22)
    fig.suptitle("数据概览 · 各组采集条件不同，柱高差不是因果效应",fontweight="bold",y=1.06)
    plots.append(("数据概览",savefig(fig,out,"01_overview")))
    # One representative timeline per dataset: longest detected dip, otherwise longest stream.
    for n,name in enumerate(datasets):
        e=events[(events.dataset==name)&(events.kind=="throughput_dip")] if len(events) else pd.DataFrame()
        stream=e.sort_values("observed_duration_s",ascending=False).stream_id.iloc[0] if len(e) else d[d.dataset.eq(name)].groupby("stream_id").size().idxmax()
        q=d[d.stream_id.eq(stream)]
        panels=[("throughput_kbps","吞吐量 / kbps"),("rssi_valid","RSSI / 源单位"),
                ("interf_avg","干扰 / 源单位"),("ack_ratio","ACK 比例"),
                ("delay_proxy_ms","counter 延迟代理 / ms"),("bitrate","音频码率档位")]
        panels=[(c,t) for c,t in panels if c in q and q[c].notna().any()]
        if "channel_busy_pct" in q:panels.append(("channel_busy_pct","信道忙占比 / %"))
        fig,axes=plt.subplots(len(panels),1,figsize=(13,2.0*len(panels)),sharex=True,squeeze=False)
        for ax,(col,label) in zip(axes[:,0],panels):
            for _,piece in q.groupby("piece",sort=False):
                ax.plot(piece.time_s,piece[col],lw=.85,color=COLORS[0])
            ax.set_ylabel(label)
            if col=="throughput_kbps" and "baseline_kbps" in q:
                ax.plot(q.time_s,q.baseline_kbps,color="#8998a4",lw=.7,label="过去10秒基线")
                ax.legend(loc="upper right",fontsize=8)
            if "stall_flag" in q and len(events):
                for _,r in events[(events.stream_id==stream)&(events.kind=="flush_run")].iterrows():
                    ax.axvspan(r.start_s,r.end_s,color="#dd6262",alpha=.15)
        axes[-1,0].set_xlabel("本链路首条上报起的相对时间 / s；长缺报处断线")
        fig.suptitle(name+" | "+str(q.condition.iloc[0])+" | h"+str(q.hdl.iloc[0])+"\n红色：持续≥0.3 s的超时放弃事件；不代表独立干扰开关",fontsize=12,y=1.01)
        fig.tight_layout()
        plots.append((name+" 代表片段",savefig(fig,out,f"0{n+2}_timeline")))
    if len(screen):
        selected=screen[screen.lag_s.eq(1)]
        pivot=selected.pivot_table(index="feature",columns="outcome",values="spearman_rho",aggfunc="median")
        if len(pivot):
            fig,ax=plt.subplots(figsize=(9,max(4,len(pivot)*.5)))
            a=ax.imshow(pivot.to_numpy(),vmin=-1,vmax=1,cmap="RdBu_r",aspect="auto")
            ax.set_xticks(range(len(pivot.columns)),pivot.columns)
            ax.set_yticks(range(len(pivot.index)),pivot.index)
            for i in range(len(pivot)):
                for j in range(len(pivot.columns)):
                    v=pivot.iloc[i,j]
                    if np.isfinite(v):ax.text(j,i,f"{v:+.2f}",ha="center",va="center")
            fig.colorbar(a,ax=ax,label="各连续区间的 Spearman ρ 中位数")
            ax.set_title("X领先Y 1秒的关联摘要 · 非因果图 / 非效应量")
            plots.append(("时滞关联",savefig(fig,out,"05_lag_associations")))
    # Physical prior graph, explicitly unrolled to avoid apparent contemporaneous feedback cycles.
    fig,ax=plt.subplots(figsize=(12.5,6.7));ax.axis("off");ax.set_xlim(0,1);ax.set_ylim(0,1)
    nodes={"env":(.18,.85,"外部干扰 / 距离\n未独立测量"),
      "load":(.79,.85,"业务下包负载\n未测量"),"radio":(.18,.58,"信道观测 t\nRSSI / 干扰"),
      "quality":(.48,.58,"传输质量 t\nACK / 接收错误"),"queue":(.79,.58,"队列等待 t\ncounter代理"),
      "ctrl":(.18,.22,"控制策略 t+1\n码率 / 功率"),"goodput":(.48,.22,"成功发送吞吐量 t+1"),
      "flush":(.79,.22,"超时放弃 t+1\n业务症状代理")}
    edges=[("env","radio"),("env","quality"),("radio","quality"),("load","queue"),("load","goodput"),
           ("quality","queue"),("quality","ctrl"),("queue","flush"),("quality","goodput"),("ctrl","goodput")]
    for src,dst in edges:
        x1,y1,_=nodes[src];x2,y2,_=nodes[dst]
        ax.annotate("",xy=(x2,y2+.065),xytext=(x1,y1-.065),
           arrowprops={"arrowstyle":"->","color":"#99a8b2","lw":1.3})
    for name,(x,y,label) in nodes.items():
        ax.text(x,y,label,ha="center",va="center",fontsize=10,
          bbox={"boxstyle":"round,pad=.7","facecolor":"#fff1dc" if name in ["env","load"] else "#e7f0f4","edgecolor":"#bacbd5"})
    ax.set_title("通信机理先验示意 · 箭头是待验证假设，非本次自动证明的因果边",fontsize=13,pad=10)
    plots.append(("机理假设",savefig(fig,out,"06_causal_hypotheses")))
    return plots

def table(df,limit=30):
    if df is None or not len(df):return "<p class='muted'>无可用记录 / 尚不满足分析条件。</p>"
    return "<div class='table'>"+df.head(limit).rename(columns={"dataset":"数据组","condition":"场景","hdl":"链路","rows":"上报数","segments":"片段数","dt_zero":"零间隔数","dt_over_gap":"长缺报数","dt_max_s":"最大间隔/s","rssi_zero":"RSSI零值数","flush_positive_reports":"放弃阳性上报","shortened_time_rows":"短写时间行数","hypothesis":"候选机制","level":"证据级别","outcome":"结果变量","lag_s":"领先秒数","strongest_descriptive_rho":"最强示例ρ","q_shift_exploratory":"探索q","next_test":"下一步验证","feature":"特征","n_blocks":"1秒块数","spearman_rho":"关联ρ","detrended_rho":"去趋势ρ"}).to_html(index=False,escape=True,float_format=lambda x:f"{x:.4g}",na_rep="—")+"</div>"+(f"<p>仅显示前 {limit} 行，完整结果见 tables/。</p>" if len(df)>limit else "")

def portable_image(path):
    return "data:image/png;base64,"+base64.b64encode(Path(path).read_bytes()).decode()

STYLE="""body{font:16px/1.7 'Microsoft YaHei','Noto Sans CJK SC',Arial,sans-serif;background:#f4f7fa;color:#183246;margin:0}
main{max-width:1200px;margin:auto;padding:38px 35px 70px;background:white}h1{font-size:36px;line-height:1.3;margin:.2em 0}
h2{font-size:24px;margin-top:2.3em;border-bottom:2px solid #c9dce7;padding-bottom:8px}h3{font-size:19px}
.kicker{color:#156b8a;font-size:14px;letter-spacing:2px}.lead{font-size:19px}.box{background:#edf4f8;padding:18px 22px;border-left:4px solid #156b8a;margin:20px 0}
.warn{background:#fff4e2;border-color:#cf8a1e}.muted{color:#667d8a}.table{overflow:auto}table{border-collapse:collapse;font-size:13px;width:100%}
td,th{border:1px solid #d9e4ea;padding:8px;text-align:left;white-space:normal}th{background:#eaf2f7}img{width:100%;height:auto}
code,pre{background:#f0f4f6;font-family:Consolas,monospace}pre{white-space:pre-wrap;padding:15px;font-size:13px}a{color:#156b8a}
details{border:1px solid #d9e4ea;padding:12px;margin:12px 0}summary{cursor:pointer;font-weight:bold}
@media print{body{background:white}main{padding:10px;max-width:none}h2{break-after:avoid}img,table{break-inside:avoid}details{display:block}}
"""


def make_case_figures(d,casebook,adapter,out):
    set_style();plots=[]
    labels={"throughput_kbps":"成功吞吐量 / kbps","stall_flag":"超时放弃代理 / 0–1",
            "latency_ms":"应用时延 / ms","rssi_valid":"信号 / 适配器单位",
            "interf_avg":"干扰 / 源单位","weighted_interf_avg":"弱干扰指标 / 源单位",
            "channel_busy_pct":"信道忙占比 / %","bitrate":"音频码率档位","pwrlev":"功率档位",
            "phy_rate_mbps":"PHY配置速率 / Mbps","ack_ratio":"ACK比例",
            "delay_proxy_ms":"等待代理 / ms"}
    for case in casebook["cases"]:
        ref=case["reference"];start=min(case["start_s"]-10,ref.get("start_s",case["start_s"]))
        end=case["end_s"]+5
        g=d[d.stream_id.eq(case["stream_id"])&d.piece.eq(case["piece"])&d.time_s.between(max(0,start),end)]
        roles=adapter.get("diagnostic_roles",{})
        fields=list(dict.fromkeys([case["outcome"]]+roles.get("interference",[])[:1]+roles.get("signal",[])[:1]+
             ["ack_ratio","delay_proxy_ms"]+roles.get("control",[])[:1]))
        fields=[x for x in fields if x in g and g[x].notna().any()][:6]
        if not fields:continue
        fig,axes=plt.subplots(len(fields),1,figsize=(12,1.7*len(fields)),sharex=True,squeeze=False)
        for ax,field in zip(axes[:,0],fields):
            ax.plot(g.time_s,g[field],lw=.85,color=COLORS[0])
            ax.axvspan(case["start_s"],case["end_s"],color="#d56060",alpha=.18)
            if ref["status"]=="selected":ax.axvspan(ref["start_s"],ref["end_s"],color="#267ca3",alpha=.14)
            ax.set_ylabel(labels.get(field,field))
        axes[-1,0].set_xlabel("同一连续链路的相对时间 / s")
        fig.suptitle(case["case_id"]+" | "+case["condition"]+" | 链路 "+case["hdl"]+
          "\n红色：分析窗口；蓝色：按固定规则选取的历史参考（非因果对照）",fontsize=11,y=1.02)
        fig.tight_layout()
        plots.append((case["case_id"],savefig(fig,Path(out),"case_"+case["case_id"])))
    return plots

def write_investigation_report(out,d,summary,casebook,capabilities,comparison,causal,plots,manifest):
    """A concise human-facing view of the machine-readable investigation artifacts."""
    contract=manifest["settings"]
    body=["<div class='kicker'>WIRELESS EXPERT INVESTIGATION · V2</div>",
      "<h1>通信问题调查</h1><p class='lead'>"+html.escape(contract["question"])+"</p>",
      "<div class='box'>任务："+html.escape(contract["task"])+" · 主结果："+html.escape(contract["primary_outcome"])+
      f" · 调查范围 {len(d):,} 条上报 · 选取 {casebook['case_count']} 个案例。"
      "诊断对比、统计关联与已识别干预效应分别记录；诊断优先级不代表因果概率。</div>",
      "<h2>执行契约与能力</h2><pre>"+html.escape(json.dumps(contract,ensure_ascii=False,indent=2))+"</pre>",
      table(pd.DataFrame(capabilities["fields"])),
      "<p>参考窗口不按候选原因或效果大小挑选：在同一连续链路内，按预先配置的窗口、间隔和配置条件寻找最近的合格历史窗口。"
      "参考采用结果清洁条件筛选，仅用于诊断，不能当作反事实或ATE对照。无合格参考时保留失败原因。</p>",
      "<h2>事件案例与竞争解释</h2>"]
    notes=["# 通信问题调查",contract["question"],"任务："+contract["task"],"主结果："+contract["primary_outcome"],
           "范围："+str(len(d))+" 条上报；契约："+contract["contract_id"],
           "诊断参考不是反事实对照；所有案例解释上限为E1，除非另有已识别的独立干预结果。"]
    if not casebook["cases"]:
        body.append("<p>本任务未产生事件案例。无事件不等于健康；设备对比与因果任务使用各自的执行计划。</p>")
    for case in casebook["cases"]:
        body.append("<h3>"+html.escape(case["case_id"])+" · "+html.escape(case["condition"])+"</h3>")
        body.append("<p>"+html.escape(f"链路 {case['hdl']}，{case['start_s']:.3f}–{case['end_s']:.3f} 秒；参考状态：{case['reference']['status']}")+"</p>")
        notes.extend(["","## "+case["case_id"],f"链路 {case['hdl']}；{case['start_s']:.3f}–{case['end_s']:.3f} 秒",
                      "参考状态："+case["reference"]["status"]+("；"+case["reference"].get("reason","") if case["reference"]["status"]!="selected" else "")])
        values=pd.DataFrame([{"metric":name,**value} for name,value in case["metrics"].items()])
        body.append(table(values[[x for x in ["metric","status","during","reference","difference","screening_threshold"] if x in values]],20))
        body.append("<p>调查决策："+html.escape(case["decision"]["status"])+"；仍保留竞争解释。</p>")
        notes.append("调查决策："+case["decision"]["status"])
        for action in case["decision"]["next_actions"]:
            notes.append("下一步："+action["action"]+"；区分："+action["distinguishes"])
        if case["reference"]["status"]!="selected" and case.get("prelude",{}).get("status")=="available_unmatched_process_context":
            body.append("<p>下表是配置未匹配的前置过程变化，只作过程描述，不能充当匹配对照。</p>")
            body.append(table(pd.DataFrame([{"metric":name,**value} for name,value in case["trajectory_deltas"].items()]),15))
        if len(case.get("configuration_phases",[]))>1:
            phases=[{"phase":p["phase"],"start_s":p["start_s"],"end_s":p["end_s"],"settings":str(p["settings"]),"reference":p["reference"]["status"]} for p in case["configuration_phases"]]
            body.append(table(pd.DataFrame(phases),20))
        claims=[]
        for h in case["hypotheses"]:
            claims.append({"候选":h["title"],"证据状态":h["status"],"复核优先级":h["review_priority"],
              "反证/限制":"；".join(h["counterevidence"]+h["limitations"]),"下一步":h["next_experiment"]})
            notes.extend(["- "+h["title"]+"："+h["status"],
                          "  支持："+json.dumps(h["support"],ensure_ascii=False,default=str),
                          "  反证/限制："+"；".join(h["counterevidence"]+h["limitations"]),
                          "  下一步："+h["next_experiment"]])
        body.append(table(pd.DataFrame(claims),10))
        for title,path in plots:
            if title==case["case_id"]:body.append("<img src='"+portable_image(path)+"'>")
    if not casebook["cases"]:
        for title,path in plots:body.append("<details><summary>"+html.escape(title)+"</summary><img src='"+portable_image(path)+"'></details>")
    body.extend(["<h2>设备对比与识别状态</h2><pre>"+html.escape(json.dumps(comparison,ensure_ascii=False,indent=2,default=str))+"</pre>",
      "<pre>"+html.escape(json.dumps(causal,ensure_ascii=False,indent=2,default=str))+"</pre>",
      "<h2>分层数据摘要</h2>",table(summary,30),
      "<h2>证据追溯</h2><p>tables/casebook.json保存完整病例、精确原始行集合、参考选择和每条主张；"
      "resolved_request.json保存实际执行设置。measurement_profiles记录打印值变化间隔，不能将它误称传感器刷新周期。"
      "evidence_revision.json对比历史主张，未出现在新范围的案例不会被当作已反驳。manifest保存输入、代码、配置和种子。</p>",
      "<p>时滞探索统一校正，多条链路不是独立实验重复。未来特征对照同样强或不可用时明确标记时间方向未分辨。"
      "缺少业务入队、独立干预或设备身份时，保留竞争解释与能力边界。</p>"])
    notes.extend(["","## 设备比较状态",json.dumps(comparison,ensure_ascii=False,indent=2,default=str),
                  "","## 因果识别状态",json.dumps(causal,ensure_ascii=False,indent=2,default=str)])
    page="<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>通信问题调查</title><style>"+STYLE+"</style><main>"+"".join(body)+"</main></html>"
    Path(out,"report.html").write_text(page,encoding="utf-8")
    Path(out,"analysis.md").write_text("\n\n".join(notes)+"\n",encoding="utf-8")

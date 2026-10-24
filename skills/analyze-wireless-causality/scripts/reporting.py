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
        means.append(np.average(q.loc[valid,"throughput_kbps"],weights=q.loc[valid,"dt"]))
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
            if "stall_flag" in q:
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

def write_report(out,d,audit,quality,npz,summary,events,screen,cards,comparison,causal,plots,manifest):
    out=Path(out)
    body=["<div class='kicker'>WIRELESS DIAGNOSTICS · REPRODUCIBLE EVIDENCE</div>",
      "<h1>通信数据专家诊断报告</h1>",
      f"<p class='lead'>协议 {html.escape(manifest['protocol'].upper())} · {len(d):,} 条上报 · {d.segment.nunique()} 个片段 · 当前因果状态：{html.escape(causal['status'])}</p>",
      "<div class='box warn'><b>结论边界：</b>本报告自动定位现象、筛选根因候选并记录证据。观测关联、时间先后与反事实因果效应分别标注。"
      "红色事件区间来自超时放弃结果，不能反过来充当外部干扰处理标签。</div>",
      "<h2>1 · 先核对数据含义</h2>",
      "<p>SLE：tx_flushed保留原始计数，并派生 &gt;0 标志；total_tx_size是成功发送字节数，按真实dt换算链路吞吐量。"
      "bitrate是源码率档位，不代表实际吞吐量。hdl是片段内链路，sn是日志字段，均不能代替物理设备身份。"
      "Wi-Fi：使用适配器指定的应用字节计数；不把PHY速率或tx_failed视为SLE的等价字段。</p>",
      "<p>短写的 mm:ss.s 时间不直接解析为完整日期；按每链路真实dt重建相对时间。原始文件及其哈希均保留。"
      "空值不补零，无发送时ACK比例留空；长缺报、非正间隔切断窗口。当前阈值是探索设置，不是业务SLA。</p>",
      table(audit[[c for c in ["dataset","rows","segments","dt_zero","dt_over_gap","dt_max_s","rssi_zero","flush_positive_reports","shortened_time_rows"] if c in audit]]),table(quality),"<h3>NPZ窗口审计</h3>",table(npz),
      "<h2>2 · 异常现象与时间定位</h2>",
      "<p>吞吐量掉坑：低于同一连续链路过去10秒活动吞吐量中位数的50%，持续至少0.3秒；基线至少30条有效记录。"
      "只有在有效上报区间内检测，不跨缺报。短片段或长期持续低吞吐可能没有有效历史基线，因此零事件不等于性能健康。"
      "业务负载未测量时，低吞吐不能单独证明链路故障。超时放弃事件同样要求持续至少0.3秒；总计数包含更短记录。</p>"]
    for title,path in plots[:1]:body.append("<h3>"+html.escape(title)+"</h3><img src='"+portable_image(path)+"'>")
    if len(events):
        event_summary=events.groupby(["dataset","kind"]).agg(events=("event_id","size"),observed_event_seconds=("observed_duration_s","sum")).reset_index()
        body.append(table(event_summary))
        top=events[events.kind.eq("throughput_dip")].sort_values("observed_duration_s",ascending=False)
        body.extend(["<h3>最长掉坑事件（选择规则公开，供专家复核）</h3>",
          table(top[[c for c in ["event_id","dataset","condition","hdl","start_s","end_s","observed_duration_s","baseline_kbps","throughput_kbps","source_row_first","source_row_last"] if c in top]],12)])
    for title,path in plots[1:]:
        body.append("<details open><summary>"+html.escape(title)+"</summary><img src='"+portable_image(path)+"'></details>")
    body.extend(["<h2>3 · 根因候选与反证路径</h2>",
      "<p>1秒不重叠窗口内汇总，覆盖率≥80%；连续段至少60秒。扫描−1、0、1、2、5秒时滞。"
      "正时滞表示特征先于结果，−1秒是未来特征对照。循环移位保留序列结构，全部检验统一BH校正；"
      "p/q仅为平稳性等假设下的探索诊断，周期性与趋势仍可能误导，不能据此升级为因果。去线性趋势后的ρ作为敏感性对照。"
      "h5/h6共享环境，不能当作两次独立试验。下表的最强关联经过搜索选择，不能作为预注册验证结果。</p>",
      table(pd.DataFrame(cards)[[c for c in ["hypothesis","level","outcome","lag_s","strongest_descriptive_rho","q_shift_exploratory","next_test"] if c in pd.DataFrame(cards)]],20),
      "<h3>强关联证据明细</h3>",
      table(screen[[c for c in ["dataset","condition","hdl","feature","outcome","lag_s","n_blocks","spearman_rho","detrended_rho","q_shift_exploratory","time_relation"] if c in screen]],15),
      "<h2>4 · 设备比较与因果识别</h2>",
      "<h3>设备比较状态</h3><pre>"+html.escape(json.dumps(comparison,ensure_ascii=False,indent=2,default=str))+"</pre>",
      "<h3>因果分析状态</h3><pre>"+html.escape(json.dumps(causal,ensure_ascii=False,indent=2,default=str))+"</pre>",
      "<p>独立干扰日志到位后，随机化配对交叉试验入口按外部ON/OFF分段，剔除预先规定的稳定时间，"
      "先合并同一会话内共享环境的链路，再求配对差；置信区间按独立会话重采样。"
      "此版本不自动把观察研究包装成随机试验，未运行PCMCI、DoWhy或SHAP。</p>",
      "<h2>5 · 下一轮最有价值的验证</h2>",
      "<ol><li>提供独立干扰开关时间戳、发射功率、信道、业务流与随机化记录，核验与日志时钟的偏差。</li>"
      "<li>补充设备型号/固件/物理序列映射、链路角色、上层下包量、编码码率和天线/位置。</li>"
      "<li>固定负载与距离，随机化干扰ON/OFF顺序；重复独立会话并轮换设备，避免把连续100ms采样当独立复制。</li>"
      "<li>以预先登记的吞吐量和真实音频卡顿为主要结果，区分超时放弃代理；留一会话验证并记录反证。</li></ol>",
      "<h2>6 · 复现与审计</h2>",
      "<p>tables/ 保存完整事件、分层汇总、关联结果和敏感性表；figures/ 保存PNG及可编辑SVG。"
      "manifest.json记录输入哈希、配置、软件版本、代码哈希、随机种子及原始输入未改变检查。"
      "结论追溯至事件ID、源文件、行号、会话与链路。报告不会将推断标签写回源数据。</p>",
      "<pre>"+html.escape(json.dumps({k:manifest[k] for k in ["protocol","seed","source_files_unchanged","settings"]},ensure_ascii=False,indent=2))+"</pre>",
      "<h2>方法依据</h2>",
      "<p>采用先明确假设与识别条件、再估计并检验稳健性的流程："
      "<a href='https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/estimating_causal_effects/index.html'>DoWhy官方文档</a>。"
      "时间序列探索需处理自相关与采样尺度："
      "<a href='https://proceedings.mlr.press/v124/runge20a.html'>Runge (2020), PCMCI+</a>。"
      "反事实与纵向因果推断基础：<a href='https://miguelhernan.org/whatifbook'>Hernán &amp; Robins, What If</a>。"
      "Wi-Fi遥测口径参见<a href='https://docs.kernel.org/driver-api/80211/cfg80211.html'>Linux cfg80211文档</a>。</p>"])
    page="<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>通信数据专家诊断</title><style>"+STYLE+"</style><main>"+"".join(body)+"</main></html>"
    (out/"report.html").write_text(page,encoding="utf-8")

"""Competing explanations with explicit evidence and limitations, never posterior causes."""
import hashlib

def assess_hypotheses(case,adapter,catalog):
    matched=case["reference"]["status"]=="selected"
    delta=case["metrics"] if matched else case.get("trajectory_deltas",case["metrics"])
    metric_table="metrics" if matched else "trajectory_deltas"
    roles=adapter.get("diagnostic_roles",{})
    def shifted(role,status):
        return [x for x in roles.get(role,[]) if delta.get(x,{}).get("status")==status]
    def available(role):
        return [x for x in roles.get(role,[]) if delta.get(x,{}).get("status") not in [None,"unmeasured_or_no_reference"]]
    def metric(name):return delta.get(name,{}).get("status")
    worse=(metric("throughput_kbps")=="down" or metric("ack_ratio")=="down" or
           metric("delay_proxy_ms")=="up" or metric("latency_ms")=="up" or metric("stall_flag")=="up")
    result=[]
    for definition in catalog["hypotheses"]:
        hid=definition["id"];support=[];against=[];limitations=[]
        status="untestable";priority="need_measurements"
        if hid in ["external_interference","path_loss","scheduler_contention"]:
            role={"external_interference":"interference","path_loss":"signal","scheduler_contention":"scheduler"}[hid]
            direction="down" if hid=="path_loss" else "up"
            changed=shifted(role,direction)
            if changed:
                support.extend([{"metric":x,"comparison":delta[x],"ref":case["case_id"]+"/"+metric_table+"/"+x} for x in changed])
                if worse:status="supported_candidate";priority="investigate"
                else:status="unresolved";limitations.append("指标发生变化，但缺少同向可靠性/结果证据")
            elif available(role):
                status="weakened_in_this_window";priority="alternative"
                against.append("选定参考与事件之间，已测相关指标未呈现预设退化方向；不能推广为排除该机制")
            else:limitations.append("缺少测量或没有满足条件的参考窗口")
            if hid=="external_interference":
                limitations.extend(["干扰指标/忙占比不是独立处理分配","同一测量族的多个指标不作为独立证据累计"])
            if hid=="path_loss":limitations.append("平均RSSI稳定不能排除多径、选择性衰落或方向差异")
            if adapter.get("protocol")=="sle":limitations.append("RX信号/接收侧扫描与TX吞吐可能方向不同，只能先作共享环境线索")
            if hid=="scheduler_contention":limitations.append("取消/异常是诊断线索，需原因码确认，不能单独当外部根因")
        elif hid=="control_response":
            changed=shifted("control","up")+shifted("control","down")
            variable=[x for x in roles.get("control",[]) if len(case["event"]["settings"].get(x,[]))>1]
            if changed or variable:
                status="observed_response";priority="investigate"
                support.append({"changed_metrics":changed,"variable_event_settings":variable})
            elif available("control"):
                status="weakened_in_this_window";priority="alternative";against.append("本窗口内配置变化未被观测到")
            limitations.append("控制变化既可能是保护响应，也可能改变业务供给；相关不能确定反向归因")
        elif hid=="demand_change":
            no_tx=case["event"].get("no_tx_all_observed")
            if no_tx is True:
                status="unresolved";priority="investigate"
                support.append("事件内所有已观测发送计数为0，兼容业务停发，也兼容未观测调度阻塞")
            else:
                status="unresolved";limitations.append("有发送记录仍不能证明应用提供了足够业务负载")
            limitations.append("没有应用入队、编码器与队列证据时，不宣称已排除需求变化")
        else:
            reset=case["event"].get("counter_reset_reports")
            ratio=case["event"]["valid_seconds"]/max(case["end_s"]-case["start_s"],1e-9)
            if reset or ratio<.8:
                status="supported_candidate";priority="investigate"
                support.append({"counter_reset_reports":reset,"valid_interval_coverage":min(ratio,1)})
            elif reset is None:
                status="unresolved";priority="need_measurements"
                limitations.append("未提供计数器重置核验记录，不能把未知当成0次重置")
                against.append("该已观测窗口上报较连续；这仅减弱大面积缺报解释")
            else:
                status="weakened_in_this_window";priority="alternative"
                against.append("该已观测窗口未见计数器重置或大面积缺报；不证明采集机制在所有时刻可靠")
        lags=[]
        for feature in roles.get({"external_interference":"interference","path_loss":"signal",
              "scheduler_contention":"scheduler","control_response":"control"}.get(hid,""),[]):
            lags.extend(case.get("context_lags",{}).get(feature,[]))
        if any(x.get("direction_warning") for x in lags):
            limitations.append("同连续段内未来特征对照同样强或不可用，时间方向未分辨")
        if not matched and hid in {"external_interference","path_loss","scheduler_contention"} and status in {"supported_candidate","weakened_in_this_window"}:
            status="unresolved";priority="investigate" if support else "need_measurements"
            against=[]
            limitations.append("仅有未匹配的前置过程变化；工作点/控制变化混杂，不能作为匹配对照证据")
        if case.get("onset_context",{}).get("focus_may_clip_existing_symptom"):
            limitations.append("窗口之前已出现症状，不能用焦点起点证明候选原因先行")
        if case["reference"]["status"]!="selected":
            limitations.append("没有合格参考窗口；不能用全局最强相关补成该事件的解释")
        digest=hashlib.sha256((case["stream_id"]+case["kind"]+str(case["start_s"])+str(case["end_s"])+hid).encode()).hexdigest()[:16]
        result.append({"claim_id":"claim_"+digest,"hypothesis_id":hid,"title":definition["title"],
          "status":status,"review_priority":priority,"evidence_level":"E1_maximum",
          "support":support,"counterevidence":against,"limitations":limitations,"context_lags":lags,
          "missing_evidence":definition["needed"],"next_experiment":definition["next_experiment"],
          "next_action_effort":definition["effort"],"root_cause_confirmed":False,
          "scope_ref":case["case_id"],"causal_effect":None})
    return sorted(result,key=lambda x:({"investigate":0,"need_measurements":1,"alternative":2}[x["review_priority"]],x["hypothesis_id"]))


def decision_for_case(case):
    """Choose discriminating evidence collection, not an uncalibrated cause winner."""
    hypotheses=case["hypotheses"]
    supported=[h["hypothesis_id"] for h in hypotheses if h["status"]=="supported_candidate"]
    unresolved=[h["hypothesis_id"] for h in hypotheses if h["status"] in ["unresolved","untestable","observed_response"]]
    actions=[]
    if case.get("onset_context",{}).get("focus_may_clip_existing_symptom"):
        actions.append({"priority":0,"action":"向前扩展过程核查，先确定最早退化和特征实际更新时间；所选焦点不是故障起点",
                        "distinguishes":"真正先行变化与退化后的伴随/控制响应","type":"onset_review"})
    if case["reference"].get("reason")=="event_settings_vary":
        actions.append({"priority":1,"action":"按配置阶段复核质量与控制变化先后；仅对稳定阶段使用各自的同配置历史参考",
                        "distinguishes":"控制策略响应、业务码率供给改变与同工作点无线退化","type":"phase_review"})
    elif case["reference"]["status"]!="selected":
        actions.append({"priority":1,"action":"补同链路、同配置、同业务口径的过去参考；说明现有参考为何不可比",
                        "distinguishes":"真实事件变化与工作点/参考选择差异","type":"data_request"})
    if case["event"].get("no_tx_all_observed"):
        actions.append({"priority":1,"action":"检查事件内应用入队、编码器和队列，确认主动停发还是阻塞",
                        "distinguishes":"业务供给停止与无线传输失败","type":"additional_logs"})
    if any(x.get("direction_warning") for values in case.get("context_lags",{}).values() for x in values):
        actions.append({"priority":2,"action":"取得独立开关/决策时间和测量更新时间，核验共同时钟",
                        "distinguishes":"真实先后与周期共同驱动/慢速更新","type":"additional_logs"})
    if {"external_interference","scheduler_contention"}.issubset(set(supported)):
        actions.append({"priority":3,"action":"先对齐干扰与取消原因码；若两者总是同步变化，设计干扰×其他业务开关的受控交叉",
                        "distinguishes":"空口干扰与共享天线/调度竞争","type":"controlled_experiment_design"})
    if not actions:
        for h in hypotheses:
            if h["review_priority"]=="investigate" or h["status"]=="untestable":
                actions.append({"priority":2,"action":h["next_experiment"],"distinguishes":h["title"]+"与剩余竞争解释",
                                "type":h["next_action_effort"]})
                if len(actions)>=2:break
    if not actions:
        actions.append({"priority":2,"action":"获取独立应用负载和事件真值，复核结果定义与工作点",
                        "distinguishes":"未测业务原因与当前已测机制","type":"additional_logs"})
    return {"status":"multiple_candidates" if len(supported)>1 else "candidate_with_unresolved_alternatives" if supported else "insufficient_discrimination",
            "supported_candidates":supported,"unresolved_alternatives":unresolved,
            "next_actions":sorted(actions,key=lambda x:x["priority"]),
            "stop_rule":"当前数据不能区分时停止升级结论；不要重复扫描直到显著","confirmed_root_cause":None}

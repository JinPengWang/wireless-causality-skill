# 病例、主张与证据更新

病例保存case_id、stream_id、piece、结果定义、时间、event/reference/metrics和hypotheses。
source_refs含源文件、链路、连续段及精确原始行集合，不只给可能夹杂另一链路的行号范围。

每条主张保存：
claim_id、hypothesis_id、status、review_priority、support、counterevidence、limitations、
missing_evidence、next_experiment、next_action_effort、scope_ref、evidence_level。
不设置未校准的因果概率或“可信度百分比”。

| 状态 | 含义 |
|---|---|
| supported_candidate | 在选定病例和参考中观察到与机制一致的变化，仍未识别因果 |
| observed_response | 观测到控制变化，原因与响应方向尚未区分 |
| weakened_in_this_window | 该窗口内已测模式不支持某个简单解释，不代表全球排除 |
| unresolved | 证据不足或竞争解释尚不能分开 |
| untestable | 缺测量或参考，不当作无效假设 |

review_priority是专家取证顺序，不能转换为根因概率。
干扰均值与weighted干扰同属一个测量族，不能将两个显著相关当两次独立实验。
时滞证据严格标为同链路、同连续段的上下文，不伪称是该短事件的充分因果检验。
固定+1与−1秒对比；未来同样强或缺失时保留方向警告，q再小也不升级证据。

reference.status=unavailable保留具体原因：缺配置、事件配置变化、覆盖不足或找不到过去窗口。
参考依结果清洁性筛选，存在选择偏差，不计算病例对照差的“因果ATE”。
自动差异阈值用作可重复筛选，不能替代专家的物理判断与干预设计。

--previous-run只读取旧病例并输出状态修订。
未出现在新范围的事件写not_in_current_scope_not_refuted；不同契约不直接当作知识反转。
新日志或新专家意见可能需要重新定义匹配、指标和估计目标；理由写入notes并保留旧运行。
没有合格参考时优先补同配置、同环境、相同负载下的历史或独立实验，不从别的设备/片段偷借正常窗口。

## 自适应事件与起点

配置变化的整个事件不可强配单一工作点。configuration_phases按控制值变化分段，各稳态段可独立寻找同配置历史参考。
prelude是同连续段之前2秒的未筛选过程，trajectory_deltas描述前置变化；没有匹配参考时机制保持unresolved，不升级为匹配证据。
人工focus之前若已报警，onset_context标记可能截断故障过程；其起点不是物理起因时间。即使候选指标在焦点内领先，也应先核查更早变化和真实测量更新时间。
同一阶段里的多个100ms样本不等于独立复制。常数聚合的浮点抖动不得制造时滞排名变化。

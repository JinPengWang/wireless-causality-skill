---
name: analyze-wireless-causality
description: Analyze wireless communication telemetry for automatic visualization, throughput dips, stutter or timeout symptoms, matched device comparisons, root-cause hypotheses, and auditable causal evidence. Use for SLE/星闪 or Wi-Fi logs, questions such as 吞吐量为什么掉坑、设备A与其他设备有什么不同、为什么卡顿、分析干扰根因, and reusable communication diagnostics. Includes protocol adapters, deterministic Python tools, guarded randomized switchback estimation, and expert validation workflows.
---

# 通信数据专家诊断

把用户问题转成可检验的通信假设，运行可复现分析，交付现象、候选机理、反证和下一步实验。
先读本文件；按任务读取下面的专项参考。不要先加载所有文档或全部原始数据。

## 执行顺序

1. **确定问题。** 区分现象定位、设备比较、预测、干预效应四种任务。
   明确结果变量、参照窗口、比较单位和目标人群。默认把“wife”理解为用户语境中的 Wi-Fi。
   缺少SLA时使用公开的探索阈值继续工作；不得称为业务故障定论。
2. **确认字段语义。** 读取同名JSON、参数表与场景图。
   SLE读 [sle-semantics.md](references/sle-semantics.md)；Wi-Fi/新协议读 [adapter-contract.md](references/adapter-contract.md)。
   使用现有数据完成可执行部分，不因缺少因果识别信息而停掉数据审计和异常诊断。
3. **运行确定性工具。** 从本技能目录定位脚本，使用当前项目Python。
   所有输出放入一个新的运行目录，保留原始文件及来源哈希。
4. **定位异常。** 读 report.html、事件表、覆盖率和敏感性表。
   复核一个强异常和一个正常/反例片段；引用 event_id、源文件、行号、时间区间及链路。
5. **生成候选机理。** 读 [diagnostic-playbooks.md](references/diagnostic-playbooks.md)。
   结合通信机理、时间先后、分层对照、反向时滞及缺失机制解释；先列竞争解释再筛选。
6. **评估因果识别。** 读 [causal-methods.md](references/causal-methods.md)。
   未满足识别条件时标为“未识别”，不输出臆造的ATE、原因概率或责任百分比。
   只有外部独立处理日志及经核验的设计支持时调用 switchback 估计器。
7. **交付专家可复核结论。** 报告事实、解释、未解决问题、最小验证实验。
   读 [expert-workflow.md](references/expert-workflow.md) 组织商业/学术结果及复核记录。

## 命令

把 <skill> 替换为此文件的父目录，把 <data> 替换为原始数据根目录。
不要使用含空格的未加引号路径。输出目录必须为空。

SLE 自动诊断：
~~~powershell
python "<skill>/scripts/analyze.py" --protocol sle --data-root "<data>" --task diagnose --output "<data>/SLE_Expert_Workbench/runs/new_run"
~~~

只做概览可用 --task overview。通过 --request 指定 assets/analysis_request.template.json 的副本调整阈值。
--task 是报告任务标记与探索开关；自然语言理解由调用此技能的Agent负责，不是脚本内置聊天服务。

Wi-Fi 映射输入：
~~~powershell
python "<skill>/scripts/analyze.py" --protocol wifi --input "<trace.csv>" --adapter "<skill>/assets/wifi_adapter.json" --task diagnose --output "<run>"
~~~

配对设备比较：
~~~powershell
python "<skill>/scripts/analyze.py" --protocol wifi --input "<trace.csv>" --task compare --output "<run>"
~~~

SLE如另有真实设备映射，提供 --device-registry，格式见 assets/device_registry.template.csv。
必须另外在适配器 matched_covariates 中明确共同条件，不得仅按设备名字比较。

独立随机干预试验：
~~~powershell
python "<skill>/scripts/analyze.py" --protocol sle --data-root "<data>" --task causal --interventions "<external_blocks.csv>" --design "<verified_design.json>" --output "<run>"
~~~

先读因果方法参考，再填写模板。不得为了通过门槛而把未验证的 false 全改为 true。

## 当前已实现的能力

- SLE base/chan/NPZ分层读取、输入哈希、时间格式与缺报审计。
- 按真实dt计算成功发送吞吐量；超时放弃计数与阳性标志分开。
- 连续观测段内掉坑检测、超时放弃事件、来源追溯和阈值敏感性。
- 1秒不重叠窗口、前后时滞Spearman筛选、循环移位探索诊断、全族BH与去趋势对照。
- 自包含HTML报告，PNG与SVG图，完整CSV/JSON审计输出。
- Wi-Fi可配置字段映射、累积计数差分和重置隔离。
- 两组设备的共同条件配对差异；按采集pair重采样，仍属描述性比较。
- 真实外部随机配对开关试验的条件因果估计，按独立session聚类。

PCMCI/PCMCI+、DoWhy-GCM、DML、倾向评分、时变处理MSM和预测模型是方法扩展点。
本版本没有执行它们，不得在报告中称“已完成”或把简单相关矩阵命名为自动因果图。

## 禁止混淆

- tx_flushed原值不是二元；stall_flag只是超时放弃代理，不是音频QoE真值。
- bitrate不是成功吞吐量；功率档位不是dBm；未确认单位的RSSI/干扰不得虚标dBm或直接相减为SNR。
- hdl不是设备，sn不是设备序列号；多个链路和100ms记录不代表独立实验重复。
- normal/fixed/mix不是天然随机对照；场景图不能证明每个文件来自图中地点。
- 不按“每30秒交替”合成干扰真值；episodes是结果派生，不能作为独立treatment。
- 不把缺报填成0吞吐量/0错误；不跨缺报、片段、会话做差分、滞后、插值或事件连接。
- NPZ缺失值使用掩码；同一原始区间产生的重叠窗口及同会话双链路必须同组切分。
- 相关、Granger、SHAP、预测精度和显著性均不能单独证明因果。
- 因果图里的控制反馈要按时间展开，不在同一时刻画未经说明的有向环。
- 不调整总效应路径上的中介或碰撞点；不默认所有特征都进入“控制变量”。

## 输出约定

每次运行产生 report.html、manifest.json、resolved_adapter.json、figures/、tables/。
重点读取 events.csv、lag_associations.csv、evidence_cards.json、causal_status.json、comparison_status.json。
未满足条件必须保留明确的 blocked/not_identified 结果，不以空白表或零效应掩盖失败。
输出目录已有文件时改用新目录；不要自动删除旧结果。

写结论时使用 E0（事实/事件）、E1（关联/机理候选）、E2（特定设计假设下识别）、E3（独立实验验证）。
E3由专家记录和新实验支持，本工具不会自动颁发。
用“在本样本/本场景中观察到”“与假设一致”“尚未排除”表述证据边界。

## 验证与扩展

执行 scripts/test_core.py 验证单位、缺报、设备比较与因果估计。
新增协议优先增加适配器，不修改共享算法中的字段含义；先用合成已知机制和缺失/重置反例验证。
新增方法必须补充所需假设、可识别条件、失败状态和独立评估集。
一个主Agent足以按角色顺序执行。只有用户或运行环境允许时才并行委派；统计计算必须来自同一版本脚本。


---
name: analyze-wireless-causality
description: >-
  Conduct question-driven wireless expert investigations: locate throughput dips or latency/stutter symptoms, explain a specified event with matched historical context and competing mechanisms, compare a device against a reference cohort, assess causal identification, and update an auditable evidence ledger. Use for SLE/星闪, Wi-Fi or an adapter-mapped protocol and questions such as 吞吐量为什么掉坑、这个事件的根因是什么、设备A与其他设备哪里不同、为什么不同. Includes executable request contracts, event cases, source-row evidence, negative checks and guarded randomized-intervention estimation.
---

# 通信问题调查

把专家问题变成可执行的调查契约，再用数据区分竞争解释。
用确定性工具计算；用领域知识提出、修正假设；保留反证和测量缺口。
不要把“生成大量图”或“找到最强相关”作为完成调查的标准。

## 1. 接收问题并选择调查路径

先区分问题中的对象和所求结论。已有上下文足够时直接执行；只询问会改变分析选择的必要信息。
“wife”在本项目语境中按Wi-Fi理解。读取源JSON和相应协议语义，不猜测设备身份或处理标签。

| 用户要回答的问题 | task | 优先产物 |
|---|---|---|
| 数据能说明什么、哪里缺报 | overview | 能力矩阵、分层摘要 |
| 哪里掉坑/卡顿、某个事件为什么 | diagnose | 事件病例、历史参考、竞争机制、反证 |
| 设备A与参照设备有什么不同 | compare | 共同条件覆盖、按采集配对的差异 |
| 关闭干扰或切策略会提高多少 | causal | 识别结果、条件效应或未识别原因 |

预测任务需另建训练/验证设计；本技能不将解释、预测与干预效应混为一谈。

读取 [investigation-contract.md](references/investigation-contract.md)，把问题写成assets中的请求模板副本。
明确primary_outcome、scope、focus、参考规则及比较单位；CLI和请求冲突、未知字段会报错，不静默忽略。
primary_outcome支持throughput_kbps、stall_flag、latency_ms；时延需给绝对阈值。
有业务SLA时优先用绝对阈值；没有时可用公开的相对探索规则，并保留持续慢速可能漏检的限制。

## 2. 核验语义和可分析能力

SLE读取 [sle-semantics.md](references/sle-semantics.md)；新协议读取 [adapter-contract.md](references/adapter-contract.md)。
检查单位、方向、累计/区间计数、时间来源、字段真实更新方式和独立实验单位。
capabilities记录缺失/常数/可变字段；measurement_profiles记录打印值变化，不能当作真实传感器刷新周期。

核心边界：
- tx_flushed保留计数，stall_flag是>0的超时放弃代理；缺QoE真值时不要直接称音频卡顿。
- bitrate不是成功吞吐量，功率档位不是dBm；未确认单位的RSSI/干扰不构造已标定SNR。
- hdl不是设备，sn不是设备身份；双链路、100ms记录、重叠NPZ窗口不是独立实验复制。
- 不把缺报填0，不跨片段/缺报/计数器重置连接事件、差分或时滞。
- fixed/normal/mix不是天然受控对照；场景图不自动赋予每个文件地点标签。

## 3. 运行最小充分分析

从本文件父目录定位脚本。输出放入新空目录；保留旧结果，不修改原始输入。
建议Windows使用python -B -X utf8。运行时输入和代码改变会使结果无效。

~~~powershell
python -B -X utf8 "<skill>/scripts/analyze.py" --data-root "<data>" --request "<request.json>" --output "<new_run>"
~~~

SLE无需额外指定适配器。Wi-Fi用：
~~~powershell
python -B -X utf8 "<skill>/scripts/analyze.py" --protocol wifi --input "<trace.csv>" --request "<request.json>" --output "<new_run>"
~~~

其他协议提供--adapter；由adapter.loader选择读取器，不修改共享算法里的协议分支。
overview、compare、causal不会隐式执行全局时滞扫描或挑选事件。diagnose仅对解析后的候选字段和主结果扫描。
candidate_causes限定统计筛选；领域竞争解释仍要保留，不能只验证用户先入为主的一个原因。

## 4. 用事件病例解释现象

读取 [diagnostic-playbooks.md](references/diagnostic-playbooks.md) 和 [evidence-contract.md](references/evidence-contract.md)。
优先读tables/casebook.json和analysis.md，再按需读全量事件与时滞表；不要把所有CSV加载进上下文。

每个病例必须具备：
1. 现象定义、时间区间、连续链路、精确原始行集合和测量口径。
2. 参考窗口选择规则、配置是否一致、覆盖率及失败原因。
3. 支持、反证、缺失信息、可检验的下一步，以及适用范围。
4. 至少考虑无线条件、控制反馈、业务供给、调度和采集等竞争解释；不可测就明确保留。

默认参考是同一连续链路内最近的合格历史窗口，隔开事件前保护间隔，并匹配预设配置。
不依据候选原因或效果大小挑参考，不使用事件后的“好窗口”替代。
参考的清洁结果筛选会造成选择偏差，因此只作诊断对照，不能当反事实或ATE控制。
没有合格参考时保留unavailable，不能用别处的全局最强相关补成该事件的根因。
事件内部配置变化时，读取configuration_phases及各阶段的单独参考；prelude/trajectory_deltas只描述前置过程，不能冒称配置匹配。
检查onset_context：人工焦点可能截取已发生故障的一部分。之前已退化时先向前复核，不以焦点起点证明特征先行。

检查固定±1秒的未来特征对照、去趋势结果、扫描/打印变化模式。
未来关联同样强或对照缺失时明确写“时间方向未分辨”，不称“领先所以致因”。
同一测量族和同环境双链路不累加为独立证据。优先级不是概率，不给“根因置信度93%”。

## 5. 公平地比较设备，再解释差异

读取 [comparison-design.md](references/comparison-design.md)。
两设备可默认按名称确定符号方向；三个及以上必须明确reference_device和目标设备。
先看共同条件覆盖率、未匹配条件和测量口径，再看差异；不自动给全体设备排冠军。
多链路先声明共同link_role或缩小范围，不能混合不同方向/角色。

SLE需要真实device_registry映射；没有身份时仍可描述链路表现，但正式设备比较返回blocked。
同一设备重复采集不代表多台同型号独立复制。CI只对已有设备/配对条件描述，不证明设备原因。
分析“为什么不同”时必须继续读取mechanism_contrasts，检查共同条件下信号/竞争/配置/可靠性代理的差异。
分开暴露条件差、工作点/控制响应差、机制差和采集差；不能直接从配置相关推断固有缺陷。
需要时间过程时，从共同条件和精确来源选择目标设备窗口，另起diagnose并聚焦该窗口；两次调查保留不同的比较单位。
共同条件下观测指标相近但结果仍不同，应明确缺少的应用/队列/实现日志，不能把“排除几个指标”写成已定位硬件缺陷。

## 6. 识别后才估计因果

读取 [causal-methods.md](references/causal-methods.md)。
先明确干预、结果、目标人群、时间尺度、混杂/中介/反馈和独立实验单位，再选设计。
当前仅实现外部随机配对开关试验的条件估计：
~~~powershell
python -B -X utf8 "<skill>/scripts/analyze.py" --data-root "<data>" --task causal --interventions "<independent_blocks.csv>" --design "<verified_design.json>" --output "<new_run>"
~~~

不能从tx_flushed、吞吐量阈值或假定周期反推出处理真值。
设计模板默认false；核验分配记录、时钟和携带效应后填写，不为通过门槛而全部改true。
质量→未来控制→未来质量必须按时间展开；估计总效应不随意调整中介/碰撞点。
识别失败时报告not_identified和最小补数/实验方案；既有诊断证据照常保留。

## 7. 更新证据并完成调查

有新日志、专家纠正或新对照时，新建运行；用--previous-run读取旧casebook进行主张状态对比。
范围/阈值变化、未选入病例不等于反驳；历史原始证据不可覆写。
需要人工改变假设或匹配集合时，在notes说明原因，不能只保留有利的一次运行。

完成前：
- 复核一个强异常和一个反例；对关键数值检查原始行和正确分母。
- 同时交付“已观测到什么、优先验证什么、尚未排除什么、下一步如何区分”。
- 有条件时检查独立重复；没有时停止在相应证据级别，不反复扫描直到显著。
- 用E0事实、E1候选、E2设计条件下识别、E3独立干预验证，E3不由本工具自动颁发。
- 无法区分时明确并列候选，输出最便宜且能区分它们的取证动作，不臆造因果结论。

## 资源与验收

- [expert-workflow.md](references/expert-workflow.md)：商业闭环、学术评估及Agent角色边界。
- [sources.md](references/sources.md)：方法来源；PCMCI、DoWhy-GCM、DML/MSM只是扩展点，尚未运行。
- assets/hypothesis_catalog.json：竞争机制、测量缺口和可检验实验。
- scripts/test_core.py与scripts/test_investigation.py：实现与推理失败模式回归测试。

一个主Agent按角色顺序执行即可。运行环境或技能验证流程允许时才委派独立任务；
不要把预设答案交给验证者，也不要让多个Agent各自搜索后挑最有利的统计结果。

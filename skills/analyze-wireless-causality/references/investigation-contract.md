# 调查契约

## 字段与实际行为

| 字段 | 行为 |
|---|---|
| task | overview/diagnose/compare/causal分别执行不同计划 |
| primary_outcome | 决定检测、统计筛选和默认设备比较的结果变量 |
| scope | dataset/condition/segment/hdl/device_id/stream_id的精确值列表；未知值报错 |
| focus.event_id | 解释当前定义下的指定事件；未检测到则报错 |
| focus.stream_id/start_s/end_s | 解释手动指定的完整测量窗口，不跨连续段 |
| detector | relative/absolute/binary；实际影响事件定义 |
| reference | window_s/lookback_s/guard_s/step_s/min_coverage/match_fields实际影响参考选择 |
| candidate_causes | 限定时滞统计筛选；不取消领域竞争解释 |
| case_budget | 自动选择病例上限，默认6；先覆盖无发送/伴超时/其他下降等症状表型，再补链路与长事件 |
| seed | 决定随机诊断/区间；CLI显式seed优先，保存最终值 |
| comparison | reference_device/target_devices/metrics/match_fields |
| question/causal_question/notes | 调查目的与专家理由，保留原文；不伪称脚本理解了自由文本 |
| lag_seconds | 包含−1、0、1秒，保留对称时序检查 |
| block_seconds | 目前固定1秒，不静默声称支持任意时标 |

CLI task与请求task冲突时拒绝。未知字段、未声明原因、身份/结果/中介冒充候选原因均拒绝。
旧版task=throughput_dip及扁平阈值兼容，但新模板优先使用2.0结构。
适配器的原始单位阈值只是探索下限，事件比较采用max(下限,2×1.4826×参考MAD)。
这不是显著性检验或已标定物理SLA；需要外部业务阈值时显式采用absolute模式。

## 调查边界

scope定义总体，focus定义解释的事件。保留总体上下文计算历史基线，不把手动焦点起点误当采集起点。
病例按症状表型、链路多样性和持续时间选择是公开的探索规则，不代表故障严重性或业务损失已经验证。
相同问题改变契约会生成不同contract_id。主张更新要同时解释契约和输入变化。

## 分层输出

先读resolved_request.json、tables/capabilities.json、tables/casebook.json和analysis.md。
按需读events、measurement_profiles、lag_associations、matched_device_pairs和manifest。
数据质量审计覆盖全部加载源；诊断结果只覆盖scope，不混称两个分母。
研究者要选择其他结果/时标/模型时，先扩展契约、语义与测试，不能让自由文本跳过实现边界。

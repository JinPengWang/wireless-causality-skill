# 协议扩展契约

## 共享模型

一行代表一个明确测量区间、会话、设备、链路、方向和场景。
保留 source_file/source_row，原始字段不覆盖，派生字段与其单位/公式分离。

| 共享角色 | SLE | Wi-Fi示例 | 迁移约束 |
|---|---|---|---|
| 有效吞吐量 | 成功发送bytes/dt | 接收端app bytes差分/dt | 层次、方向、重传和协议头含义要一致 |
| 配置速率 | 音频bitrate档位 | PHY MCS/NSS/GI/速率 | 不是同一量，分别保留 |
| 信号 | rssi_avg原值 | 已标定rssi_dbm | 单位明确后才做物理运算 |
| 干扰/竞争 | interf_avg | busy time、noise、扫描 | 忙占比不是干扰功率 |
| 可靠性 | tx_ack/tx_total、rx_per | retries、failed、PER | 分母和方向需审计，不默认同义 |
| 症状 | 超时放弃代理 | 应用中断/失败计数 | Wi-Fi失败计数不自动等价卡顿 |
| 调度 | counter差、取消计数 | airtime、queue、MAC延迟 | 驱动计数器语义不同 |
| 身份 | 需外部设备映射 | device_id/session/link | 逻辑接口不是设备型号 |

## Wi-Fi CSV输入

最低字段：timestamp、device_id、session_id、scenario、link_id，以及至少一个可分析结果。
内置吞吐量适配器期待app_rx_bytes_total；单调累积、byte单位。
相同时间戳重复先明确聚合策略，工具默认拒绝；不会任取一行。
负差分为计数器重置，不换算成负速率；未知位宽不推断回绕。
只在同设备、会话、场景、链路内差分。缺失字段保留NaN并降低能力，不自动合成传感器。

设备比较额外要求scenario、pair_id、firmware、band_ghz、channel_width_mhz、offered_load_mbps。
pair_id标识真实采集配对；每个条件内两设备都必须观测。缺少共同支持会返回blocked。
想比较固件效应时，不能同时把固件当必须相同的匹配变量；先写新的estimand并修改匹配设计。
需要额外控制距离/天线/方向/温度时在matched_covariates加入，不能宣称默认列表涵盖所有混杂。

## 新增适配器

复制wifi_adapter.json并显式写identity/metrics/kind/unit/scale/causal_candidates/matched_covariates。
支持gauge、cumulative_count、cumulative_bytes、interval_count、interval_bytes。字节计数单位必须byte，区间/差分字节按scale/dt换算；计数归一化按其定义使用。
添加新loader只负责格式→共享模型，保留数据质量状态，不把因果逻辑藏进导入器。
跨协议只比较同定义结果；协议原生指标用于各自机理解释。
最小验收：单位换算、零分母、缺失、重置、重复时间、多设备隔离、缺报断段、已知合成机理。

## 官方语义依据

Linux cfg80211把tx_bytes、tx_packets、tx_retries、tx_failed、signal、txrate等分别提供。
使用这些字段前核对驱动实现、计数累计范围及其更新方式；txrate不是应用接收吞吐量。
参考 https://docs.kernel.org/driver-api/80211/cfg80211.html

## V2扩展要求

声明diagnostic_roles（signal/interference/control/scheduler）、diagnostic_match_fields及diagnostic_thresholds。角色决定哪些领域假设能被检验；缺角色保持不可检验，不靠列名碰巧相似推断。
阈值为原始单位探索下限，必须结合数据来源和参考MAD复核，不是通用物理阈值。
自定义protocol配合loader=mapped_csv即可复用共享流程，无需增加CLI协议分支。
没有吞吐量但有应用时延时可用latency_ms加absolute阈值；未测字段保留缺失。

测量刷新周期如果有原始时间戳，应另行声明。measurement_profiles只是打印值变化统计，恒定值不能证明传感器没有更新。

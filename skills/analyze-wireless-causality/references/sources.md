# 方法来源（2026-10-23核查）

1. Hernán MA, Robins JM (2020). Causal Inference: What If.
   https://miguelhernan.org/whatifbook
   用于反事实、可交换性、positivity及纵向处理思路。
2. Runge J (2020). Discovering contemporaneous and lagged causal relations in autocorrelated nonlinear time series datasets.
   PMLR 124:1388–1397. https://proceedings.mlr.press/v124/runge20a.html
   PCMCI+为可选扩展；本文要求因果充分性等条件。本技能并未运行该算法。
3. Sharma A, Kiciman E (2020). DoWhy: An End-to-End Library for Causal Inference.
   https://arxiv.org/abs/2011.04216
   参考建模→识别→估计→反证的分析流程，不把库名当因果保证。
4. PyWhy, Estimating Causal Effects, official documentation.
   https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/estimating_causal_effects/index.html
5. Blöbaum P et al. (2022). DoWhy-GCM: An extension of DoWhy for causal inference in graphical causal models.
   https://arxiv.org/abs/2206.06821
   可选异常/分布变化归因；需先验证结构及机制，不等于SHAP归因。
6. Linux kernel, cfg80211 subsystem.
   https://docs.kernel.org/driver-api/80211/cfg80211.html
   用于核对Wi-Fi signal、txrate、字节与重试统计的独立语义。

项目私有依据：SLE参数对照表_0813.xlsx的SLE Log Params第10–33行；
三个数据目录各自base/chan/dynamics/episodes JSON；场景介绍.png；当前用户采集说明。
不访问参数表内未提供内容的内部wiki，不假称阅读内部标准。

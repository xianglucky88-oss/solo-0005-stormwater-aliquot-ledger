# 当前数据契约

流量段内按匀速解释；确定触发只计算至首个流量缺口，后段仍可贡献单段已知水量。严格核对现场、转运、实验室交接及方法保持时间；浓度仅按自己代表的触发体积加权。低于报告限是闭包上下界，不是测定零。

结构与字段示例以 `examples/baseline.json` 为准。`changed.json` 是可合法发布的另一个输入；`invalid.json` 是必须拒绝的反例。

独立核对值：已知体积 72 L，确定累计前缀 52 L；m1 支撑 30 L、负荷 [20,50] mg。改版 b4 缺少实验室交接后流量不变，m1 只支撑 20 L、负荷 [0,30] mg。

## 再起涨与有证分段

一场雨可在断流后再次起涨。输入可选地给出两个成对参数（要么都给，要么都不给；不给时报表与历史契约逐字节保持原样）：

- `dry_seconds`：运行方选定的最短有证断流时长 D（整数秒，≥1）。
- `window_seconds`：运行方选定的统计评估窗 W（整数秒，≥1）。

时间轴被规范为三类：有流量 `flow`、有证零流 `zero`（`units: 0`，零是测定值不是缺测）、缺测 `missing`（`units: null`，绝不按零处理）。一个零流/缺测区间只在**同时**满足下列条件时才判为 `certified` 分段并真正切开场次：

1. 区间两侧都存在起涨（首尾的零流不算）；
2. 区间是连续有证零流，且时长 ≥ D；
3. 时长 ≥ W，即再起涨前长度 W 的评估窗完全落在该有证零流内。

其余情况只记录为 `split_candidates` 中的 `uncertain` 证据：缺测区间给 `missing_evidence`，零流不足 D 给 `below_minimum_duration`，零流不足以容纳评估窗给 `assessment_window_incomplete`，两侧无起涨给 `not_between_two_rises`。**记录缺口只能证明"分段仍不确定"，永不产生分段边界。**

## 跨断流触发的水量与负荷

触发体积按原始标定流量在各段间精确切分（有理数，非整数用 JSON 字符串输入），并在触发上以 `segments` 给出每段升数、以 `crosses_split` 标识是否跨段；各段升数之和恒等于触发体积。

- 单段触发（`single_segment`）：负荷按既有规则整段归属。
- 跨段触发但**没有**额外有证组成条件（`unsplit_cross_split`）：水量按段列出，但每段 `concentration_mg_l` 与 `load_mg` 为 `null`；整触发负荷保留在方法级 `cross_split_unsplit`，不按水量分摊浓度。
- 跨段触发且化验另附有证 `composition`（`split_by_composition`）：组成必须覆盖该触发的每一段，逐段给出独立的 `measured`/`below_limit` 浓度上下界，负荷按"该段升数 × 该段浓度"独立计算。组成是更细的独立证据，其分段负荷之和不必等于按整瓶浓度推算的事件负荷，两者在 `reconciliation` 中分列。

## 对账

分段模式额外输出 `reconciliation`：

- 水量硬对账：各段已知体积之和 = 场次已知体积；每个触发的分段升数之和 = 触发体积；各段锚定体积之和 = 场次锚定前缀（缺测之后的水量只计入已知量、不计入锚定量）。
- 负荷对账：单段归属负荷 + 跨段未拆负荷 + 有证组成拆分负荷，与事件口径分方法列示并闭合。
- 瓶分类：`single_segment`、`cross_split`、`no_bottle`、`unconfirmed`；跨段瓶集合与跨段化验证据集合必须一致。任一硬对账失败即以状态 2 拒绝发布。

## 验收输入对

`examples/segmented_dry.json` 与 `examples/segmented_gap.json` 是同水量（80 L）、同瓶链、同化验的孪生输入，唯一差别是 t=20–30 的 10 秒区间：

- `segmented_dry.json`：有证零流，达到 D=W=10，判 `certified`，切成两段；触发 3 跨段（5 L+5 L）。a3 带 `composition` 按段拆 m1 负荷（25+15 mg）；a8 无组成，水量按段拆而 m2 段负荷为 `null`、整触发 90 mg 留在未拆池。
- `segmented_gap.json`：同一区间改为缺测，只产生 `uncertain/missing_evidence`，不切分；锚定前缀止于 25 L，其后瓶全部 `unconfirmed`、相关化验不可用。

入口为 `aliquot/cli.py`，归约编排在 `aliquot/workflow.py`。有理数输出为整数或 `分子/分母` 字符串；输入的精确非整数应使用 JSON 字符串。不将 `null` 当作零。SQLite 每版保留规范化输入、成果及两者的 SHA-256；这是本地完整性核对，不是数字签名。

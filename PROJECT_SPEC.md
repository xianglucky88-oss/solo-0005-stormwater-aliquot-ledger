# 当前数据契约

流量段内按匀速解释；确定触发只计算至首个流量缺口，后段仍可贡献单段已知水量。严格核对现场、转运、实验室交接及方法保持时间；浓度仅按自己代表的触发体积加权。低于报告限是闭包上下界，不是测定零。

结构与字段示例以 `examples/baseline.json` 为准。`changed.json` 是可合法发布的另一个输入；`invalid.json` 是必须拒绝的反例。

独立核对值：已知体积 72 L，确定累计前缀 52 L；m1 支撑 30 L、负荷 [20,50] mg。改版 b4 缺少实验室交接后流量不变，m1 只支撑 20 L、负荷 [0,30] mg。

入口为 `aliquot/cli.py`，归约编排在 `aliquot/workflow.py`。有理数输出为整数或 `分子/分母` 字符串；输入的精确非整数应使用 JSON 字符串。不将 `null` 当作零。SQLite 每版保留规范化输入、成果及两者的 SHA-256；这是本地完整性核对，不是数字签名。

# 双采样计划配对契约（`examples/paired.json`）

同一事件两套独立采样计划：各自的触发体积、瓶链、方法与化验记录放在 `plans` 两个元素内，事件窗口与 `liters_per_unit` 标定在顶层共享。两计划在重叠时段必须报告相同的体积速率（双方同为缺口的时段除外），否则以状态 2 拒绝；单侧缺口与有证流量重叠也拒绝。

## 同一条可证累计水量轴

每计划只把首个缺口前的锚定前缀（`anchored_liters`）作为有绝对坐标的连续有证段写入 `certified_axis`；缺口后的有证段仍计入 `known_liters`，但坐标原点不可证，不能放上共享轴。两计划有证段的几何交叠给出 `overlap_certified_liters`。

## 共同支持子体积是几何分母

触发编号是各计划的本地标签，**不允许用编号求交**。共同支持只按触发体积区间的几何交叠计算，并同时要求：落在两计划有证轴内、且两侧该区间都有 `supported` 化验。结果：

- `common_support_liters`：真实共同支持子体积（分母），按原子片段列入 `common_pieces`，每片段标注两侧实际命中的本地触发号；
- `cross_number_matches`：编号不同却几何交叠的命中，证明对账基于体积而非编号；
- `same_number_without_common`：编号碰巧相同但无共同支持的对，区分 `no_geometric_overlap`、`one_side_not_supported`、`overlap_not_supported` 三种原因；
- `method_loads_on_own_support`：两侧方法各自在自身支持体积上的负荷，与共同分母分开列。

## 何时才能重算共同负荷

仅当顶层 `bottle_mixed` 对两侧都为 `true`（协议注明瓶内混匀、允许子体积重算）且 `common_support_liters > 0` 时，才把两侧浓度逐片段切到同一子体积上重算 `common_load_mg`，并给出 `load_difference_mg` 闭包（planA − planB）。否则 `recomputable=false`，`common_load_mg` 为 `null`，原因取 `plan_protocol_does_not_permit_subvolume_recompute` 或 `no_common_supported_subvolume`；交叠有证水量与各方法自有支持量仍分开可查。

真实零结果（`measured` 且 `mg_l=0`）是测定值，闭包为 [0,0] 且照常计入分母；`below_limit` 保持 [0, 检出限] 闭包；`null` 永不解释为零。


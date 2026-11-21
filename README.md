# 雨水流量与分样数据账

从标定流量、采瓶链与化验上下界发布有证负荷，而非全事件负荷。 使用合成资料。无需联网、账户或第三方 Python 依赖；已验证 Python 3.14。

```sh
python3 -m aliquot preview examples/baseline.json
python3 -m aliquot publish examples/baseline.json ledger.sqlite original
python3 -m aliquot publish examples/changed.json ledger.sqlite revised
python3 -m aliquot history ledger.sqlite
python3 -m aliquot show ledger.sqlite original
python3 -m aliquot source ledger.sqlite original
python3 -m aliquot replay ledger.sqlite revised
```

`preview` 不写库；`show` 读已发布成果，`source` 读随版封存的输入，`replay` 重算并核对。`publish` 不覆盖已用版名。命令在输入错误时以状态 2 退出，不发布结果。重复演示请换版名或用新库。

## 双计划配对

`examples/paired.json` 是同一事件的两套独立采样计划（不同触发体积、独立瓶链与方法记录），放在同一条可证累计水量轴上对账：

```sh
python3 -m aliquot preview examples/paired.json
python3 -m aliquot publish examples/paired.json ledger.sqlite pair-original
python3 -m aliquot replay ledger.sqlite pair-original
```

成果中的 `pairing` 字段：`certified_axis` 给出各计划可放上共享轴的连续有证段；`overlap_certified_liters` 是交叠有证水量；`common_support_liters` 是以真实几何交叠（而非触发编号求交）得到的共同支持子体积；`same_number_without_common` 与 `cross_number_matches` 分别记录同号无共同支持、异号却交叠的审计证据。仅当 `bottle_mixed` 两侧皆为真时才在共同分母上重算 `common_load_mg` 与负荷差闭包，否则只分开列交叠水量与各方法自有支持量。规则细节见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。

样本字段及成果口径见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。这里的规则仅用于合成数据，并非真实业务规范。

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

两站同场降雨负荷比较（站间时延只知连续范围，全场共用同一时延；不写库）：

```sh
python3 -m aliquot compare examples/pair-witness.json
python3 -m aliquot compare examples/pair-conflict.json
python3 -m aliquot compare examples/pair-uneven.json
```

`compare` 给出对齐后的共同支持范围与负荷差封套，并对"最小时延共同支持 + 差额界线"的联合条件判定：可行则给见证时延，不可行则给冲突及两个单条件可行集；全程按连续分段线性精确求解，不采样。`pair-conflict.json` 是各单项可达、联合不可达的验收输入。

`preview` 不写库；`show` 读已发布成果，`source` 读随版封存的输入，`replay` 重算并核对。`publish` 不覆盖已用版名。命令在输入错误时以状态 2 退出，不发布结果。重复演示请换版名或用新库。

样本字段及成果口径见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。这里的规则仅用于合成数据，并非真实业务规范。

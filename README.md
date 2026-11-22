# 雨水流量与分样数据账

从标定流量、采瓶链与化验上下界发布有证负荷，而非全事件负荷。 使用合成资料。无需联网、账户或第三方 Python 依赖；已验证 Python 3.14。

```sh
python3 -m aliquot preview examples/baseline.json
python3 -m aliquot preview examples/blanks.json
python3 -m aliquot publish examples/baseline.json ledger.sqlite original
python3 -m aliquot publish examples/changed.json ledger.sqlite revised
python3 -m aliquot publish examples/blanks.json ledger.sqlite blanks
python3 -m aliquot history ledger.sqlite
python3 -m aliquot show ledger.sqlite original
python3 -m aliquot source ledger.sqlite original
python3 -m aliquot replay ledger.sqlite revised
python3 -m unittest discover -s tests
```

`preview` 不写库；`show` 读已发布成果，`source` 读随版封存的输入，`replay` 重算并核对。`publish` 不覆盖已用版名。命令在输入错误时以状态 2 退出，不发布结果。重复演示请换版名或用新库。补交空白按 `(method, batch)` 一对多引用，原负荷不变、另记校正负荷；缺空白视为未知而非零，详见规范。

样本字段及成果口径见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。这里的规则仅用于合成数据，并非真实业务规范。

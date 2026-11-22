# 雨水流量与分样数据账

从标定流量、采瓶链与化验上下界发布有证负荷，而非全事件负荷。 使用合成资料。无需联网、账户或第三方 Python 依赖；已验证 Python 3.14。

```sh
python3 -m aliquot preview examples/baseline.json
python3 -m aliquot publish examples/baseline.json ledger.sqlite original
python3 -m aliquot publish examples/changed.json ledger.sqlite revised
python3 -m aliquot preview examples/aliquots.json
python3 -m aliquot history ledger.sqlite
python3 -m aliquot show ledger.sqlite original
python3 -m aliquot source ledger.sqlite original
python3 -m aliquot replay ledger.sqlite revised
```

`preview` 不写库；`show` 读已发布成果，`source` 读随版封存的输入，`replay` 重算并核对。`publish` 不覆盖已用版名。命令在输入错误时以状态 2 退出，不发布结果。重复演示请换版名或用新库。

样本字段及成果口径见 [PROJECT_SPEC.md](PROJECT_SPEC.md)。分装链（来源、是否充分混匀、各次转交）见 `examples/aliquots.json`，规则测试：`python3 -m unittest discover -s tests`。这里的规则仅用于合成数据，并非真实业务规范。

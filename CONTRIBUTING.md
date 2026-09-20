# Contributing

此仓库维护 `aquaproj/aqua-registry` 的下载镜像投影，不直接维护上游包定义。新增或修正包元数据，请优先提交到 [aquaproj/aqua-registry](https://github.com/aquaproj/aqua-registry)。

本仓库接受镜像策略、转换器、验证器、自动化和文档改进。提交前请运行：

```sh
python3 -m pip install --requirement requirements-dev.txt
aqua install --only-link
python3 -m unittest discover -s tests -v
actionlint
python3 scripts/mirror.py --dry-run
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

如果改动会改变生成结果，再执行 `python3 scripts/mirror.py` 和 `argd gr`，并提交对应的 `pkgs/` 与 `registry.yaml` 更新。转换结果必须保持幂等，且不得绕过私有 GitHub 包、校验材料或 aqua JSON Schema 的保护。

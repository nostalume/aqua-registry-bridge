# aqua-registry-bridge

`aquaproj/aqua-registry` 的镜像桥接仓库，用于在 GitHub 或部分上游下载源访问受限时，为 [aqua](https://aquaproj.github.io/) 提供可复现的自定义 Registry。

- 上游 Registry：[aquaproj/aqua-registry](https://github.com/aquaproj/aqua-registry)
- 镜像策略：[mirror.yaml](mirror.yaml)
- 维护与架构决策：[docs/maintenance.md](docs/maintenance.md)

## 工作方式

| 输入类型 | 桥接方式 |
|---|---|
| `github_release`、`github_archive`、`github_content` | 投影为 `type: http`，下载 URL 使用 GitHub 代理，同时保留仓库元数据 |
| checksum、签名、provenance 等下载材料 | 与主资产一起投影或改写到代理 URL |
| Node.js、Haskell 等显式 HTTP URL | 按 `mirror.yaml` 的前缀映射改写 |

脚本只修改 `pkgs/**/registry.yaml`；根目录的 `registry.yaml` 由官方 `argd gr` 重新生成。转换必须可重复执行且字节级幂等，写入前会先解析并验证所有包文件。

## 使用

aqua 把自定义 Registry 的 `ref` 当作不可变引用，因此请使用本仓库发布的 `mirror-YYYYMMDD` tag 或完整 commit SHA，不要使用 `main`。下面使用一个已发布 tag 作为示例：

```yaml
registries:
  - name: mirror
    type: github_content
    repo_owner: nostalume
    repo_name: aqua-registry-bridge
    ref: mirror-20260703
    path: registry.yaml

packages:
  - name: BurntSushi/ripgrep@14.1.1
    registry: mirror
```

自定义 Registry 还需要由 aqua Policy 明确放行：

```yaml
---
registries:
  - name: mirror
    type: github_content
    repo_owner: nostalume
    repo_name: aqua-registry-bridge
    path: registry.yaml
packages:
  - registry: mirror
```

若 Policy 位于 Git 仓库根目录，检查内容后执行：

```sh
aqua policy allow /absolute/path/to/aqua-policy.yaml
```

也可以通过 `AQUA_POLICY_CONFIG` 指向可信的 Policy 文件。详见 aqua 的 [自定义 Registry](https://aquaproj.github.io/docs/develop-registry/)、[Registry 配置](https://aquaproj.github.io/docs/reference/config/#registries)和 [Policy as Code](https://aquaproj.github.io/docs/guides/policy-as-code/) 文档。

## 本地维护

需要 Python 3；`argd` 和 `actionlint` 固定在 `aqua.yaml` 中：

```sh
python3 -m pip install --requirement requirements-dev.txt
aqua install --only-link
python3 -m unittest discover -s tests -v
actionlint
python3 scripts/mirror.py --dry-run
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

应用策略并重新生成聚合 Registry：

```sh
python3 scripts/mirror.py
argd gr
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

每日同步工作流从上游构建隔离快照，通过单元测试、幂等性、JSON Schema 和聚合一致性校验后，才以普通 fast-forward/原子 push 发布提交与新的不可变 tag。GitHub Release 不是 aqua 使用自定义 Registry 的必要条件。

## License

[MIT](LICENSE)

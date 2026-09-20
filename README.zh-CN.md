# aqua-registry-bridge

[English](README.md) | [简体中文](README.zh-CN.md)

`aqua-registry-bridge` 是为 [aqua](https://aquaproj.github.io/) 生成的兼容 Registry。它从 [`aquaproj/aqua-registry`](https://github.com/aquaproj/aqua-registry) 同步包定义，并将支持的下载路径改写到代理或镜像端点，适用于 GitHub Releases 或部分上游下载服务器访问缓慢、不可用的网络环境。

本仓库镜像的是 **Registry 元数据，而不是二进制文件**。实际下载由 [mirror.yaml](mirror.yaml) 中配置的端点提供，目前包括 `gh-proxy.org` 和部分 USTC 镜像。使用前请评估这些信任边界。

## 快速开始

以下步骤会创建项目级 aqua 配置，通过 aqua Policy 放行这个非标准 Registry，安装 ripgrep 并验证结果。示例固定使用不可变 Registry tag `mirror-20260920`，已在本地 aqua v2.59.0 和 CI aqua v2.63.0 上验证。

### 1. 安装 aqua

选择一个 aqua 官方支持的安装方式：

```sh
# 使用 Homebrew 的 macOS 或 Linux
brew install aqua

# 使用 WinGet 的 Windows
winget install aquaproj.aqua

# 使用 Scoop 的 Windows
scoop bucket add main
scoop install main/aqua
```

官方安装器、预编译二进制等其他方式请参考 [安装 aqua](https://aquaproj.github.io/docs/install/)。

确认 `aqua` 命令可用：

```sh
aqua --version
```

### 2. 将 aqua 管理的工具加入 `PATH`

Linux 和 macOS 请把下面一行加入 shell 配置文件，然后重启 shell：

```sh
export PATH="$(aqua root-dir)/bin:$PATH"
```

Windows PowerShell 当前会话可执行：

```powershell
$aquaBin = Join-Path (aqua root-dir) 'bin'
$Env:Path = "$aquaBin;$Env:Path"
```

需要永久生效时，请把等价命令写入 PowerShell profile。`aqua root-dir` 返回的目录用于存放 aqua 创建的命令链接和已安装工具。

### 3. 创建或进入 Git 项目

aqua 会从 Git 仓库根目录发现项目 Policy。新项目可执行：

```sh
mkdir aqua-bridge-example
cd aqua-bridge-example
git init
```

如果项目已经有 `.git` 目录，请直接在该项目中执行后续步骤。

### 4. 创建 `aqua.yaml`

在项目根目录创建 `aqua.yaml`：

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/aquaproj/aqua/c76aafc5ccc7eee49a6f1a3a1249df69de45a4da/json-schema/aqua-yaml.json
checksum:
  enabled: true
registries:
  - name: bridge
    type: github_content
    repo_owner: nostalume
    repo_name: aqua-registry-bridge
    ref: mirror-20260920
    path: registry.yaml
packages:
  - name: BurntSushi/ripgrep@14.1.1
    registry: bridge
```

Registry 字段含义如下：

| 字段 | 必需值或用途 |
|---|---|
| `name` | 本地标识符；包通过 `registry: bridge` 选择此 Registry。 |
| `type` | 必须为 `github_content`，aqua 会从 GitHub 获取 `registry.yaml`。 |
| `repo_owner` | GitHub 所有者：`nostalume`。 |
| `repo_name` | GitHub 仓库：`aqua-registry-bridge`。 |
| `ref` | 不可变的 `mirror-YYYYMMDD` tag 或完整 commit SHA；不要使用 `main` 或 `master`。 |
| `path` | 从仓库根目录计算的 Registry 文件路径：`registry.yaml`。 |

包名和版本使用 aqua 的常规语法。必须显式设置 `registry: bridge`；否则 aqua 会从名为 `standard` 的 Registry 解析该包。

### 5. 创建 `aqua-policy.yaml`

aqua v2 默认只允许 Standard Registry。在同一个 Git 仓库根目录创建 `aqua-policy.yaml`：

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/aquaproj/aqua/c76aafc5ccc7eee49a6f1a3a1249df69de45a4da/json-schema/policy.json
registries:
  - name: bridge
    type: github_content
    repo_owner: nostalume
    repo_name: aqua-registry-bridge
    path: registry.yaml
packages:
  - registry: bridge
```

该 Policy 允许来自这个特定 GitHub Registry 的包。如果只想放行 ripgrep，把最后两行替换为：

```yaml
packages:
  - name: BurntSushi/ripgrep
    registry: bridge
```

Policy 负责标识被信任的仓库和路径，`aqua.yaml` 负责固定精确的不可变 tag。每次修改 Policy 后，都必须重新检查并放行。

### 6. 检查并放行 Policy

批准前请先阅读 `aqua-policy.yaml`。Linux 或 macOS：

```sh
aqua policy allow "$(pwd)/aqua-policy.yaml"
```

PowerShell：

```powershell
$policy = (Resolve-Path .\aqua-policy.yaml).Path
aqua policy allow $policy
```

aqua 会针对 Policy 的精确内容保存批准状态。之后只要 Policy 内容发生变化，批准就会失效，必须重新运行 `aqua policy allow`。

### 7. 解析、安装并验证

首先确认 aqua 能加载固定的 Registry 并找到 ripgrep。

Linux 或 macOS：

```sh
aqua -c aqua.yaml list | grep '^bridge,BurntSushi/ripgrep$'
```

PowerShell：

```powershell
aqua -c .\aqua.yaml list | Select-String '^bridge,BurntSushi/ripgrep$'
```

预期结果：

```text
bridge,BurntSushi/ripgrep
```

安装配置中的包并运行：

```sh
aqua -c aqua.yaml install
rg --version
```

请从项目根目录执行这些命令，以便 aqua-proxy 发现该项目的配置。`rg --version` 应显示 ripgrep 14.1.1。`aqua install` 会访问网络、在 `$(aqua root-dir)/bin` 下创建命令链接，并可能写入 aqua 的下载及包缓存。

## 添加到已有 aqua 项目

把 `bridge` 条目合并到现有 `registries` 列表，并为需要使用本 Registry 的每个包设置 `registry: bridge`。同一份 aqua 配置中的 Registry 名称必须唯一。

```yaml
registries:
  # 保留项目原有的 Registry 条目，然后增加此条目。
  - name: bridge
    type: github_content
    repo_owner: nostalume
    repo_name: aqua-registry-bridge
    ref: mirror-20260920
    path: registry.yaml

packages:
  # 保留项目原有的包条目。
  - name: BurntSushi/ripgrep@14.1.1
    registry: bridge
```

同时把对应的 `bridge` Registry 和包权限合并到仓库根目录的 `aqua-policy.yaml`，检查内容后重新执行 `aqua policy allow`。

如果配置文件不叫 `aqua.yaml`，或者不在当前目录，请使用 `aqua -c /path/to/config.yaml ...` 显式指定，也可以设置 `AQUA_CONFIG`。

## 固定与升级 Registry

aqua 把 Registry ref 视为不可变引用。本仓库只在通过验证的上游快照发生变化时发布 `mirror-YYYYMMDD`。

1. 检查可用的 [Registry tags](https://github.com/nostalume/aqua-registry-bridge/tags) 和仓库变更。
2. 把 `aqua.yaml` 中的 `ref` 替换为选定 tag。
3. 运行 `aqua -c aqua.yaml list`，确认 Registry 可以解析。
4. 运行 `aqua -c aqua.yaml install`，同步已安装工具。
5. 提交经过检查的 `aqua.yaml` 变更。

也可以固定完整 commit SHA：

```yaml
ref: ee5a9e3712c3a137b568e2b643e3b275b765fc90
```

不要使用 `main` 等分支。aqua 会在 `ref` 不变的前提下缓存 Registry 数据，并会明确拒绝 `github_content` Registry 使用 `main` 或 `master`。

Registry 固定和包版本固定是两件事。更新 Registry 不会改变写成 `name@version` 的包；只有在确实需要升级工具时，才应有意识地修改包版本。

## 桥接原理

| 上游定义 | 生成后的桥接行为 |
|---|---|
| `github_release`、`github_archive`、`github_content` | 投影为 `type: http`；下载 URL 使用配置的 GitHub 代理，同时保留 aqua 所需的仓库元数据。 |
| checksum、签名、provenance 等下载材料 | 对支持的定义，与主资产一起改写。 |
| 显式 Node.js、Haskell 下载 URL | 按 [mirror.yaml](mirror.yaml) 中有序的前缀映射改写。 |
| 私有 GitHub 包 | 转换器拒绝处理，因为匿名 HTTP 代理不等同于经过认证的 GitHub 下载。 |

转换器只修改 `pkgs/**/registry.yaml`。根目录 `registry.yaml` 由官方 `argd gr` 重新生成。发布工作流会使用 aqua 官方 JSON Schema 验证全部包文件，检查聚合等价性与幂等性，然后创建不可变 tag；不会强制推送，也不会移动已有 tag。

## 安全与信任模型

使用本 Registry 会在 aqua 上游之外增加以下信任关系：

- GitHub 从本仓库提供固定 tag 对应的 Registry 元数据。
- 代理和镜像运营方提供改写后的下载 URL。
- 上游包项目仍然是发布工具和验证材料的来源。
- 本仓库的工作流与维护者控制生成映射及发布 tag。

Checksum、Cosign、Minisign、SLSA 和 artifact attestation 的行为取决于每个上游 Registry 定义，以及 aqua 对投影后 HTTP 包的支持情况。请保持 aqua 验证功能开启，检查 `mirror.yaml`，固定 Registry ref 和包版本，并仅在相应代理/镜像运营方符合你的威胁模型时使用本服务。

## 故障排查

### `ref cannot be main or master`

改用已发布的 `mirror-YYYYMMDD` tag 或完整 commit SHA。aqua 将 Registry ref 视为不可变，因此不支持分支引用。

### `this package isn't allowed`

确认 `aqua-policy.yaml` 位于 Git 仓库根目录，包含相同的 Registry 所有者、仓库名和路径，并允许目标包。每次修改 Policy 后都要检查文件并重新运行 `aqua policy allow`。

### Registry 能加载，但包仍从 `standard` 解析

给该包增加 `registry: bridge`。在每个文件中，包的 `registry` 值都必须指向同一文件内声明的 Registry `name`。

### GitHub Registry 下载失败

确认所选 tag 存在，并确认机器可以访问 GitHub API。用 `aqua -c aqua.yaml list` 测试准确的配置。本 Registry 是公开仓库，不需要 token；私有 `github_content` Registry 则需要 `AQUA_GITHUB_TOKEN` 或 `GITHUB_TOKEN`。

### 包资产下载失败或超时

检查对 `mirror.yaml` 中各端点的访问，尤其是 `https://gh-proxy.org`。成功获取 Registry 只能证明 GitHub 提供了 `registry.yaml`；包资产使用的是独立代理或镜像端点。

### 已安装 `rg`，但找不到命令

确认 `$(aqua root-dir)/bin` 已加入 `PATH`，然后启动新 shell，或在当前会话重新执行第 2 步的 PATH 命令。

## 维护者工作流

前置条件包括 Python 3、aqua、Git，以及 [AGENTS.md](AGENTS.md) 要求的 aqua 源码检出。工具版本固定在 [aqua.yaml](aqua.yaml)，Python 验证依赖固定在 [requirements-dev.txt](requirements-dev.txt)。

```sh
python3 -m pip install --requirement requirements-dev.txt
aqua install --only-link
python3 -m unittest discover -s tests -v
actionlint
python3 scripts/mirror.py --dry-run
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

应用投影并重新生成聚合 Registry：

```sh
python3 scripts/mirror.py
argd gr
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

定时工作流先在只读任务中构建隔离快照、转换并验证，再把带哈希的 artifact 传递给单独的写权限发布任务。快照有变化时，发布普通提交和原子的 `mirror-YYYYMMDD` tag；没有变化时不发布；如果当天 tag 已经指向其他提交，则失败而不会移动 tag。

设计边界和后续工作请参阅[维护决策](docs/maintenance.md)。

## 参考资料

- [安装 aqua](https://aquaproj.github.io/docs/install/)
- [开发自定义 Registry](https://aquaproj.github.io/docs/develop-registry/)
- [aqua 配置与 `github_content`](https://aquaproj.github.io/docs/reference/config/)
- [Registry 配置参考](https://aquaproj.github.io/docs/reference/registry-config/)
- [Policy as Code](https://aquaproj.github.io/docs/guides/policy-as-code/)

## 许可证

[MIT](LICENSE)

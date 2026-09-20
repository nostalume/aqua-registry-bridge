# Maintenance decisions

本文记录 `aqua-registry-bridge` 的稳定边界和后续维护方向。它补充 README，不替代 aqua 上游规范。

## 已确定的设计

- `aquaproj/aqua-registry` 是包定义的权威输入；本仓库只拥有镜像策略、投影代码、验证代码和生成结果。
- `scripts/mirror.py` 只处理 `pkgs/**/registry.yaml`。每个文件只解析一次，先计算并验证全库结果，再开始写入，避免半完成状态。
- aqua 的 GitHub 包类型不会采用额外注入的 `url`。因此公开的 `github_release`、`github_archive` 和 `github_content` 下载配置会投影为 `http`；`repo_owner`、`repo_name` 等元数据继续用于版本发现或验证。
- GitHub release checksum 中的 `{{.Asset}}` 会改写为 HTTP checksum 渲染器支持的 `{{.AssetURL}}`，从而跟随版本/平台覆盖后的实际主资产 URL。
- 私有 GitHub 包不能安全地通过匿名 HTTP 代理等价转换，转换器对此采取 fail-closed，而不是静默生成可能泄露或失效的 URL。
- `github_url_mode: host_path` 是默认代理模式。它生成 `https://gh-proxy.org/github.com/...`，避免完整 URL 模式中的 `https:` 被 aqua 当成 Windows 缓存路径的一部分。
- 根 `registry.yaml` 始终由官方 `argd gr` 从包文件生成，不由自定义拼接逻辑维护。
- `argd gr` 在 Windows 与 Linux 上可能产生不同的包列表顺序；列表顺序没有 Registry 语义，因此跨平台门禁比较包定义多集，发布工作流的 Linux runner 是远端文件顺序的规范生成环境。
- 验证门包括：单元/回归测试、转换幂等性、无残留直连 GitHub 下载 URL、aqua 官方 JSON Schema，以及根 Registry 与所有包文件的语义多集一致性。

## 发布与兼容性

- 自定义 Registry 通过 `github_content` 使用，`ref` 必须是不可变 tag 或 commit SHA；不支持把 `main` 当作消费引用。
- 发布 tag 格式保持为 `mirror-YYYYMMDD`。同一天出现不同目标提交时工作流会失败，不会删除、覆盖或移动既有 tag。
- 已验证快照与发布权限分属两个 job；发布使用普通提交，并以 atomic push 同时写入 `main` 和新 tag。禁止 force push。
- aqua 只要求仓库中存在可引用的 tag；GitHub Release 不是此 Registry 的发布契约，因此不再每日创建 Release。
- 仓库从 `aqua-registry-mirror` 更名为 `aqua-registry-bridge` 后，现有旧 URL 依赖 GitHub 的重定向兼容。新配置应尽快改用新名称，并继续固定不可变 ref。

## 后续维护清单

1. 定期刷新固定的 aqua Schema commit、aqua/argd 版本和 GitHub Actions SHA；通过 Dependabot PR 审阅 action 更新。
2. 监控代理的可用性、速率限制和域名策略；若增加备用代理，先定义明确的选择和故障语义，避免静默切换信任边界。
3. 为 `github_archive`、`github_content`、checksum、cosign、minisign、SLSA 和 artifact attestation 增加更多真实安装样本，覆盖 Linux、macOS 与 Windows。
4. 上游出现新的 Registry 字段或包类型时，先以官方 Schema 和 aqua 行为测试确认语义，再扩展投影遍历规则。
5. 观察首次新工作流运行的权限、artifact、原子 push 和 tag 结果；本地校验不能替代 GitHub 托管运行证据。

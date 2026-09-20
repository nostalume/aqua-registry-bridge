# aqua-registry-bridge

[English](README.md) | [简体中文](README.zh-CN.md)

`aqua-registry-bridge` is a generated compatibility registry for [aqua](https://aquaproj.github.io/). It mirrors package definitions from [`aquaproj/aqua-registry`](https://github.com/aquaproj/aqua-registry) and rewrites supported download routes to proxy or mirror endpoints. It is intended for networks where GitHub Releases or selected upstream download servers are slow or unavailable.

This repository mirrors **registry metadata, not binaries**. Downloads are served by the endpoints configured in [mirror.yaml](mirror.yaml), currently including `gh-proxy.org` and selected USTC mirrors. Review those trust boundaries before use.

## Quick start

The following walkthrough creates a project-local aqua configuration, allows this non-standard Registry through aqua Policy, installs ripgrep, and verifies the result. The examples use the immutable Registry tag `mirror-20260920` and were verified with aqua v2.59.0 locally and v2.63.0 in CI.

### 1. Install aqua

Use one of aqua's officially documented installation methods:

```sh
# macOS or Linux with Homebrew
brew install aqua

# Windows with WinGet
winget install aquaproj.aqua

# Windows with Scoop
scoop bucket add main
scoop install main/aqua
```

Other installation methods, including the official installer and prebuilt binaries, are documented in [Install aqua](https://aquaproj.github.io/docs/install/).

Confirm that the `aqua` executable is available:

```sh
aqua --version
```

### 2. Add aqua-managed tools to `PATH`

On Linux and macOS, add this line to your shell profile, then restart the shell:

```sh
export PATH="$(aqua root-dir)/bin:$PATH"
```

For the current PowerShell session on Windows:

```powershell
$aquaBin = Join-Path (aqua root-dir) 'bin'
$Env:Path = "$aquaBin;$Env:Path"
```

Persist the equivalent command in your PowerShell profile if required. The directory returned by `aqua root-dir` is where aqua creates command links and stores installed tools.

### 3. Create or enter a Git project

aqua discovers a project Policy from the Git repository root. If this is a new project:

```sh
mkdir aqua-bridge-example
cd aqua-bridge-example
git init
```

If the project already has a `.git` directory, run the remaining commands from that project.

### 4. Create `aqua.yaml`

Create `aqua.yaml` in the project root:

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

The Registry fields have the following meaning:

| Field | Required value or purpose |
|---|---|
| `name` | A local identifier. Packages select this Registry with `registry: bridge`. |
| `type` | Must be `github_content` because aqua retrieves `registry.yaml` from GitHub. |
| `repo_owner` | GitHub owner: `nostalume`. |
| `repo_name` | GitHub repository: `aqua-registry-bridge`. |
| `ref` | An immutable `mirror-YYYYMMDD` tag or full commit SHA. Never use `main` or `master`. |
| `path` | Registry file path from the repository root: `registry.yaml`. |

Package names and versions use aqua's normal syntax. The explicit `registry: bridge` is important: without it, aqua resolves the package from the Registry named `standard`.

### 5. Create `aqua-policy.yaml`

aqua v2 allows only the Standard Registry by default. Create `aqua-policy.yaml` in the same Git repository root:

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

This Policy allows packages from this specific GitHub Registry. To allow only ripgrep, replace the last two lines with:

```yaml
packages:
  - name: BurntSushi/ripgrep
    registry: bridge
```

The Policy intentionally identifies the repository and path while `aqua.yaml` pins the exact immutable tag. If you change the Policy file, aqua requires you to review and allow it again.

### 6. Review and allow the Policy

Read `aqua-policy.yaml` before approving it. On Linux or macOS:

```sh
aqua policy allow "$(pwd)/aqua-policy.yaml"
```

On PowerShell:

```powershell
$policy = (Resolve-Path .\aqua-policy.yaml).Path
aqua policy allow $policy
```

Approval is stored by aqua for the exact Policy contents. A later Policy modification invalidates the approval until `aqua policy allow` is run again.

### 7. Resolve, install, and verify

First confirm that aqua can load the pinned Registry and find ripgrep.

Linux or macOS:

```sh
aqua -c aqua.yaml list | grep '^bridge,BurntSushi/ripgrep$'
```

PowerShell:

```powershell
aqua -c .\aqua.yaml list | Select-String '^bridge,BurntSushi/ripgrep$'
```

Expected line:

```text
bridge,BurntSushi/ripgrep
```

Install the configured package and run it:

```sh
aqua -c aqua.yaml install
rg --version
```

Run these commands from the project root so aqua-proxy discovers this project's configuration. `rg --version` should report ripgrep 14.1.1. `aqua install` performs network downloads, creates command links under `$(aqua root-dir)/bin`, and may populate aqua's download and package caches.

## Add the Registry to an existing aqua project

Merge the `bridge` entry into the existing `registries` list, then set `registry: bridge` on each package that should use this Registry. Registry names must be unique inside one aqua configuration.

```yaml
registries:
  # Keep the project's existing Registry entries, then add this one.
  - name: bridge
    type: github_content
    repo_owner: nostalume
    repo_name: aqua-registry-bridge
    ref: mirror-20260920
    path: registry.yaml

packages:
  # Keep the project's existing package entries.
  - name: BurntSushi/ripgrep@14.1.1
    registry: bridge
```

Also merge the matching `bridge` Registry and package permission into the repository-root `aqua-policy.yaml`, review it, and run `aqua policy allow` again.

When the configuration is not named `aqua.yaml` or is not in the current directory, select it explicitly with `aqua -c /path/to/config.yaml ...` or set `AQUA_CONFIG`.

## Pinning and upgrading the Registry

aqua treats Registry refs as immutable. This repository publishes `mirror-YYYYMMDD` only when a validated upstream snapshot changes.

1. Review the available [Registry tags](https://github.com/nostalume/aqua-registry-bridge/tags) and repository changes.
2. Replace the `ref` in `aqua.yaml` with the selected tag.
3. Run `aqua -c aqua.yaml list` to confirm Registry resolution.
4. Run `aqua -c aqua.yaml install` to reconcile installed tools.
5. Commit the reviewed `aqua.yaml` change.

You may pin a full commit SHA instead of a tag:

```yaml
ref: ee5a9e3712c3a137b568e2b643e3b275b765fc90
```

Do not use a branch such as `main`. aqua caches Registry data under the assumption that `ref` is immutable, and aqua explicitly rejects `main` and `master` for `github_content` Registries.

Registry pinning and package pinning are separate. Updating the Registry does not change a package written as `name@version`; edit the package version deliberately when you want to upgrade that tool.

## How the bridge works

| Upstream definition | Generated bridge behavior |
|---|---|
| `github_release`, `github_archive`, `github_content` | Projected to `type: http`; download URLs use the configured GitHub proxy while repository metadata remains available where aqua needs it. |
| Checksums, signatures, provenance, and related downloaded material | Rewritten together with the primary asset when the definition is supported. |
| Explicit Node.js and Haskell download URLs | Rewritten according to the ordered prefix mappings in [mirror.yaml](mirror.yaml). |
| Private GitHub packages | Rejected by the transformer because anonymous HTTP proxying is not equivalent to authenticated GitHub downloads. |

Only `pkgs/**/registry.yaml` is transformed. The root `registry.yaml` is regenerated by the official `argd gr` command. The publication workflow validates all package files against aqua's official JSON Schema, checks aggregate equivalence and idempotence, and then creates an immutable tag without force-pushing or moving an existing tag.

## Security and trust model

Using this Registry adds trust beyond upstream aqua:

- GitHub serves the pinned Registry metadata from this repository.
- Proxy and mirror operators serve transformed download URLs.
- Upstream package projects remain the source of the released tools and verification material.
- This repository's workflow and maintainers control the generated mapping and published tags.

Checksum, Cosign, Minisign, SLSA, and artifact-attestation behavior depends on each upstream Registry definition and what aqua supports for the projected HTTP package. Keep aqua's verification features enabled, review `mirror.yaml`, pin Registry refs and package versions, and use this service only if the listed proxy/mirror operators fit your threat model.

## Troubleshooting

### `ref cannot be main or master`

Use a published `mirror-YYYYMMDD` tag or a full commit SHA. Branch refs are not supported because aqua treats Registry refs as immutable.

### `this package isn't allowed`

Confirm that `aqua-policy.yaml` is in the Git repository root, contains the same Registry owner/name/path, and permits the package. Review the file and rerun `aqua policy allow` after every Policy change.

### The Registry loads, but the package is resolved from `standard`

Add `registry: bridge` to that package entry. In each file, the package's `registry` value must refer to a Registry `name` declared in that same file.

### GitHub Registry download fails

Confirm that the selected tag exists and that the machine can reach the GitHub API. Test the exact configuration with `aqua -c aqua.yaml list`. This Registry is public and does not require a token; private `github_content` Registries require `AQUA_GITHUB_TOKEN` or `GITHUB_TOKEN`.

### Package asset download fails or times out

Check access to the endpoints in `mirror.yaml`, especially `https://gh-proxy.org`. A successful Registry lookup proves only that GitHub served `registry.yaml`; package assets use separate proxy or mirror endpoints.

### `rg` is installed but the command is not found

Ensure `$(aqua root-dir)/bin` is on `PATH`, then start a new shell or apply the PATH command from step 2 to the current session.

## Maintainer workflow

Prerequisites are Python 3, aqua, Git, and the aqua source checkout required by [AGENTS.md](AGENTS.md). Tool versions are pinned in [aqua.yaml](aqua.yaml), and Python validation dependencies are pinned in [requirements-dev.txt](requirements-dev.txt).

```sh
python3 -m pip install --requirement requirements-dev.txt
aqua install --only-link
python3 -m unittest discover -s tests -v
actionlint
python3 scripts/mirror.py --dry-run
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

To apply a projection and regenerate the aggregate Registry:

```sh
python3 scripts/mirror.py
argd gr
python3 scripts/validate.py --schema .ai/aqua/json-schema/registry.json
```

The scheduled workflow builds an isolated snapshot, transforms and validates it in a read-only job, then transfers a hashed artifact to a separate write-scoped publication job. On a changed snapshot it publishes a normal commit and an atomic `mirror-YYYYMMDD` tag. On no change it publishes nothing; if the day's tag already points elsewhere, it fails instead of moving the tag.

See [maintenance decisions](docs/maintenance.md) for design boundaries and follow-up work.

## References

- [aqua installation](https://aquaproj.github.io/docs/install/)
- [Develop a custom Registry](https://aquaproj.github.io/docs/develop-registry/)
- [aqua configuration and `github_content`](https://aquaproj.github.io/docs/reference/config/)
- [Registry configuration reference](https://aquaproj.github.io/docs/reference/registry-config/)
- [Policy as Code](https://aquaproj.github.io/docs/guides/policy-as-code/)

## License

[MIT](LICENSE)

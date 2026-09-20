#!/usr/bin/env python3
"""Project aqua Registry downloads onto configured mirror endpoints.

The transformer preserves comments and formatting by using PyYAML's marked node
tree only to calculate small scalar/line edits. Package files are the sole input;
the aggregate registry.yaml is generated separately by the official `argd gr`
command.
"""

from __future__ import annotations

import argparse
import difflib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
GITHUB_TYPES = frozenset({"github_release", "github_archive", "github_content"})
AUXILIARY_KEYS = ("checksum", "slsa_provenance", "minisign")
COSIGN_FILE_KEYS = ("signature", "certificate", "key", "bundle")
ASSET_REFERENCE = re.compile(r"{{\s*\.Asset\s*}}")


class ProjectionError(ValueError):
    """The source cannot be projected without weakening its package contract."""


@dataclass(frozen=True)
class Mirror:
    original: str
    mirror: str


@dataclass(frozen=True)
class LineDiff:
    lineno: int
    before: str
    after: str


@dataclass
class Config:
    mirrors: list[Mirror] = field(default_factory=list)
    github_url_prefix: str = ""
    github_url_mode: str = "host_path"


@dataclass
class FileResult:
    path: Path
    original: str
    modified: str

    @property
    def changed(self) -> bool:
        return self.original != self.modified


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    replacement: str


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_config(path: Path) -> Config:
    data = yaml.load(_read_utf8(path), Loader=YAML_LOADER) or {}
    if not isinstance(data, dict):
        raise ProjectionError(f"{path}: configuration root must be a mapping")
    raw = data.get("mirrors", []) or []
    if not isinstance(raw, list):
        raise ProjectionError(f"{path}: mirrors must be a list")
    mirrors = [
        Mirror(str(item["original"]), str(item["mirror"]))
        for item in raw
        if isinstance(item, dict)
        and "original" in item
        and "mirror" in item
        and str(item["original"]) != str(item["mirror"])
    ]
    # Keep the original key as a compatibility alias for existing users. Its
    # historical full-URL behavior remains available explicitly.
    using_legacy_key = "github_url_prefix" not in data and "github_release_url_prefix" in data
    prefix = data.get("github_url_prefix", data.get("github_release_url_prefix", ""))
    mode = str(data.get("github_url_mode") or ("full_url" if using_legacy_key else "host_path"))
    if mode not in {"host_path", "full_url"}:
        raise ProjectionError(f"{path}: github_url_mode must be host_path or full_url")
    return Config(mirrors=mirrors, github_url_prefix=str(prefix or "").rstrip("/"), github_url_mode=mode)


def _apply_mirrors(value: str, mirrors: Iterable[Mirror]) -> str:
    for mirror in mirrors:
        if value.startswith(mirror.original):
            return mirror.mirror + value[len(mirror.original) :]
    return value


def _parse_document(content: str) -> tuple[Node | None, Any]:
    loader = YAML_LOADER(content)
    try:
        node = loader.get_single_node()
        if node is None:
            return None, None
        return node, loader.construct_document(node)
    finally:
        loader.dispose()


def _mapping_nodes(node: MappingNode) -> dict[str, tuple[ScalarNode, Node]]:
    return {
        key.value: (key, value)
        for key, value in node.value
        if isinstance(key, ScalarNode)
    }


def _mapping_items(node: MappingNode, data: dict[str, Any], key: str) -> list[tuple[MappingNode, dict[str, Any]]]:
    entry = _mapping_nodes(node).get(key)
    values = data.get(key)
    if not entry or not isinstance(entry[1], SequenceNode) or not isinstance(values, list):
        return []
    return [
        (child_node, child_data)
        for child_node, child_data in zip(entry[1].value, values)
        if isinstance(child_node, MappingNode) and isinstance(child_data, dict)
    ]


def _quote_like(node: ScalarNode, value: str) -> str:
    if node.style == "'":
        return "'" + value.replace("'", "''") + "'"
    if node.style == '"':
        import json

        return json.dumps(value, ensure_ascii=False)
    if value.startswith("{{"):
        import json

        return json.dumps(value, ensure_ascii=False)
    return value


def _insert_scalar(value: str) -> str:
    if value.startswith("{{"):
        import json

        return json.dumps(value, ensure_ascii=False)
    return value


def _proxy(prefix: str, url: str, mode: str) -> str:
    target = url.removeprefix("https://") if mode == "host_path" else url
    return f"{prefix.rstrip('/')}/{target}"


def _github_url(package: dict[str, Any], prefix: str, mode: str) -> tuple[str, str | None]:
    package_type = str(package.get("type", ""))
    owner = str(package.get("repo_owner", ""))
    repo = str(package.get("repo_name", ""))
    if not owner or not repo:
        raise ProjectionError(f"{package_type} package is missing repo_owner or repo_name")
    if package_type == "github_release":
        asset = str(package.get("asset", ""))
        if not asset:
            raise ProjectionError(f"github_release package {owner}/{repo} is missing asset")
        url = f"https://github.com/{owner}/{repo}/releases/download/{{{{.Version}}}}/{asset}"
        return _proxy(prefix, url, mode), None
    if package_type == "github_archive":
        # This is aqua's fallback URL and supports both tag names and commit IDs.
        url = f"https://github.com/{owner}/{repo}/archive/{{{{.Version}}}}.tar.gz"
        return _proxy(prefix, url, mode), "tar.gz"
    if package_type == "github_content":
        path = str(package.get("path", ""))
        if not path:
            raise ProjectionError(f"github_content package {owner}/{repo} is missing path")
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{{{{.Version}}}}/{path}"
        return _proxy(prefix, url, mode), None
    raise ProjectionError(f"unsupported GitHub package type: {package_type}")


def _github_release_file_url(
    downloaded_file: dict[str, Any],
    package: dict[str, Any],
    prefix: str,
    mode: str,
    *,
    checksum: bool = False,
) -> str:
    owner = str(downloaded_file.get("repo_owner") or package.get("repo_owner") or "")
    repo = str(downloaded_file.get("repo_name") or package.get("repo_name") or "")
    asset = str(downloaded_file.get("asset") or "")
    if checksum:
        match = ASSET_REFERENCE.match(asset)
        if match:
            explicit_owner = downloaded_file.get("repo_owner")
            explicit_repo = downloaded_file.get("repo_name")
            package_owner = str(package.get("repo_owner") or "")
            package_repo = str(package.get("repo_name") or "")
            if (explicit_owner and str(explicit_owner) != package_owner) or (
                explicit_repo and str(explicit_repo) != package_repo
            ):
                raise ProjectionError("dynamic checksum asset in another repository cannot be projected to HTTP")
            # HTTP checksum templates expose AssetURL, not Asset. Building on the
            # rendered primary URL also preserves inherited version/OS overrides.
            return "{{.AssetURL}}" + asset[match.end() :]
        if ASSET_REFERENCE.search(asset):
            raise ProjectionError("dynamic checksum asset must start with {{.Asset}}")
    if not owner or not repo or not asset:
        raise ProjectionError("github_release verification file is missing repository identity or asset")
    return _proxy(
        prefix,
        f"https://github.com/{owner}/{repo}/releases/download/{{{{.Version}}}}/{asset}",
        mode,
    )


def _effective(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    result = dict(parent)
    child_type = child.get("type")
    if child_type and child_type != result.get("type"):
        for key in ("url", "path", "asset", "crate", "cargo", "format"):
            result.pop(key, None)
    result.update(child)
    return result


class Projector:
    def __init__(self, content: str, config: Config, source: str) -> None:
        self.content = content
        self.config = config
        self.source = source
        self.newline = "\r\n" if "\r\n" in content else "\n"
        self.edits: dict[tuple[int, int], Edit] = {}
        self.claimed_spans: set[tuple[int, int]] = set()

    def add_edit(self, edit: Edit) -> None:
        span = (edit.start, edit.end)
        previous = self.edits.get(span)
        if previous is not None:
            if previous.replacement != edit.replacement:
                raise ProjectionError(f"{self.source}: conflicting edits at byte {edit.start}")
            return
        self.edits[span] = edit

    def replace_scalar(self, node: Node, value: str) -> None:
        if not isinstance(node, ScalarNode):
            raise ProjectionError(f"{self.source}: expected a scalar value")
        span = (node.start_mark.index, node.end_mark.index)
        self.claimed_spans.add(span)
        self.add_edit(Edit(*span, _quote_like(node, value)))

    def set_fields(self, node: MappingNode, values: dict[str, str]) -> None:
        entries = _mapping_nodes(node)
        pending: list[tuple[str, str]] = []
        for key, value in values.items():
            if key in entries:
                self.replace_scalar(entries[key][1], value)
            else:
                pending.append((key, value))
        if not pending:
            return
        anchor = entries.get("type")
        if anchor is None:
            anchor = next(
                (
                    (key_node, value_node)
                    for key_node, value_node in node.value
                    if isinstance(value_node, ScalarNode) and value_node.style not in {"|", ">"}
                ),
                None,
            )
        if anchor is None:
            indent = " " * node.start_mark.column
            addition = (self.newline + indent).join(
                f"{key}: {_insert_scalar(value)}" for key, value in pending
            )
            addition += self.newline + indent
            index = node.start_mark.index
            self.add_edit(Edit(index, index, addition))
            return
        if not isinstance(anchor[1], ScalarNode):
            raise ProjectionError(f"{self.source}: projected mapping has no scalar insertion anchor")
        indent = " " * anchor[0].start_mark.column
        addition = "".join(
            f"{self.newline}{indent}{key}: {_insert_scalar(value)}" for key, value in pending
        )
        index = anchor[1].end_mark.index
        self.add_edit(Edit(index, index, addition))

    def project_downloaded_file(
        self,
        node: MappingNode,
        data: dict[str, Any],
        package: dict[str, Any],
        *,
        checksum: bool = False,
    ) -> None:
        if data.get("type") != "github_release":
            return
        url = _github_release_file_url(
            data,
            package,
            self.config.github_url_prefix,
            self.config.github_url_mode,
            checksum=checksum,
        )
        self.set_fields(node, {"type": "http", "url": url})

    def project_verification(self, node: MappingNode, data: dict[str, Any], package: dict[str, Any]) -> None:
        entries = _mapping_nodes(node)
        for key in AUXILIARY_KEYS:
            value = data.get(key)
            entry = entries.get(key)
            if isinstance(value, dict) and entry and isinstance(entry[1], MappingNode):
                self.project_downloaded_file(entry[1], value, package, checksum=key == "checksum")
                if key == "checksum":
                    self.project_nested_verifiers(entry[1], value, package)
        cosign = data.get("cosign")
        cosign_entry = entries.get("cosign")
        if isinstance(cosign, dict) and cosign_entry and isinstance(cosign_entry[1], MappingNode):
            self.project_cosign(cosign_entry[1], cosign, package)

    def project_cosign(self, node: MappingNode, data: dict[str, Any], package: dict[str, Any]) -> None:
        entries = _mapping_nodes(node)
        for key in COSIGN_FILE_KEYS:
            value = data.get(key)
            entry = entries.get(key)
            if isinstance(value, dict) and entry and isinstance(entry[1], MappingNode):
                self.project_downloaded_file(entry[1], value, package)

    def project_nested_verifiers(self, node: MappingNode, data: dict[str, Any], package: dict[str, Any]) -> None:
        entries = _mapping_nodes(node)
        cosign = data.get("cosign")
        cosign_entry = entries.get("cosign")
        if isinstance(cosign, dict) and cosign_entry and isinstance(cosign_entry[1], MappingNode):
            self.project_cosign(cosign_entry[1], cosign, package)
        minisign = data.get("minisign")
        minisign_entry = entries.get("minisign")
        if isinstance(minisign, dict) and minisign_entry and isinstance(minisign_entry[1], MappingNode):
            self.project_downloaded_file(minisign_entry[1], minisign, package)

    def project_scope(self, node: MappingNode, data: dict[str, Any], effective: dict[str, Any]) -> None:
        package_type = effective.get("type")
        inactive = (
            effective.get("version_constraint") == "false"
            or bool(effective.get("no_asset"))
            or bool(effective.get("error_message"))
        )
        completed_by_runtime_override = bool(data.get("overrides")) and (
            (package_type == "github_release" and not effective.get("asset"))
            or (package_type == "github_content" and not effective.get("path"))
        )
        if package_type in GITHUB_TYPES and not inactive and not completed_by_runtime_override:
            identity = f"{effective.get('repo_owner', '?')}/{effective.get('repo_name', '?')}"
            if effective.get("private"):
                raise ProjectionError(
                    f"{self.source}: private GitHub package {identity} cannot be projected to an unauthenticated HTTP URL"
                )
            url, required_format = _github_url(
                effective, self.config.github_url_prefix, self.config.github_url_mode
            )
            fields = {"type": "http", "url": url}
            if required_format and not effective.get("format"):
                fields["format"] = required_format
            self.set_fields(node, fields)
        self.project_verification(node, data, effective)

    def project_package(self, node: MappingNode, package: dict[str, Any]) -> None:
        self.project_scope(node, package, package)
        for override_node, override in _mapping_items(node, package, "overrides"):
            self.project_scope(override_node, override, _effective(package, override))
        for version_node, version in _mapping_items(node, package, "version_overrides"):
            effective_version = _effective(package, version)
            self.project_scope(version_node, version, effective_version)
            for override_node, override in _mapping_items(version_node, version, "overrides"):
                self.project_scope(override_node, override, _effective(effective_version, override))

    def rewrite_scalar_urls(self, node: Node, *, downloadable: bool = False) -> None:
        if isinstance(node, MappingNode):
            for key, value in node.value:
                child_downloadable = isinstance(key, ScalarNode) and key.value in {"url", "opts"}
                self.rewrite_scalar_urls(value, downloadable=child_downloadable)
            return
        if isinstance(node, SequenceNode):
            for value in node.value:
                self.rewrite_scalar_urls(value, downloadable=downloadable)
            return
        if not downloadable or not isinstance(node, ScalarNode) or not isinstance(node.value, str):
            return
        span = (node.start_mark.index, node.end_mark.index)
        if span in self.claimed_spans:
            return
        rewritten = _apply_mirrors(node.value, self.config.mirrors)
        if rewritten != node.value:
            self.replace_scalar(node, rewritten)

    def render(self, root_node: Node | None, root_data: Any) -> str:
        if root_node is None:
            return self.content
        if not isinstance(root_node, MappingNode) or not isinstance(root_data, dict):
            raise ProjectionError(f"{self.source}: registry root must be a mapping")
        if self.config.github_url_prefix:
            for package_node, package in _mapping_items(root_node, root_data, "packages"):
                self.project_package(package_node, package)
        self.rewrite_scalar_urls(root_node)
        result = self.content
        for edit in sorted(self.edits.values(), key=lambda item: (item.start, item.end), reverse=True):
            result = result[: edit.start] + edit.replacement + result[edit.end :]
        return result


def process_content(content: str, config: Config, source: str = "<memory>") -> str:
    try:
        root_node, root_data = _parse_document(content)
    except yaml.YAMLError as exc:
        raise ProjectionError(f"{source}: invalid YAML: {exc}") from exc
    return Projector(content, config, source).render(root_node, root_data)


def process_file(path: Path, config: Config) -> FileResult:
    original = _read_utf8(path)
    return FileResult(path, original, process_content(original, config, str(path)))


def apply_result(result: FileResult, dry_run: bool, repo_root: Path) -> bool:
    if not result.changed:
        return False
    relative = result.path.relative_to(repo_root)
    if dry_run:
        sys.stdout.writelines(
            difflib.unified_diff(
                result.original.splitlines(keepends=True),
                result.modified.splitlines(keepends=True),
                fromfile=f"a/{relative.as_posix()}",
                tofile=f"b/{relative.as_posix()}",
                n=2,
            )
        )
    else:
        result.path.write_text(result.modified, encoding="utf-8", newline="")
    return True


def find_registry_files(repo_root: Path) -> list[Path]:
    return sorted((repo_root / "pkgs").glob("**/registry.yaml"))


def cmd_restore(repo_root: Path) -> int:
    subprocess.run(["git", "-C", str(repo_root), "restore", "--source=HEAD", "--", "pkgs", "registry.yaml"], check=True)
    return 0


def cmd_apply(config_path: Path, repo_root: Path, dry_run: bool) -> int:
    if not config_path.is_file():
        print(f"Error: mirror config not found: {config_path}", file=sys.stderr)
        return 1
    try:
        config = load_config(config_path)
    except (OSError, ProjectionError, yaml.YAMLError) as exc:
        print(f"Error: invalid mirror config: {exc}", file=sys.stderr)
        return 1
    if not config.mirrors and not config.github_url_prefix:
        print("No active mirror mappings found.")
        return 0
    files = find_registry_files(repo_root)
    try:
        # Validate every result before writing any file.
        results = [process_file(path, config) for path in files]
    except (OSError, ProjectionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    modified = sum(apply_result(result, dry_run, repo_root) for result in results)
    action = "would be modified" if dry_run else "modified"
    print(f"{modified}/{len(files)} package registry files {action}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project aqua package downloads through configured mirrors.")
    parser.add_argument("--repo-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("-c", "--config", type=Path, metavar="FILE", help="mirror policy (default: REPO/mirror.yaml)")
    parser.add_argument("-d", "--dry-run", action="store_true", help="print a diff without writing files")
    parser.add_argument("-r", "--restore", action="store_true", help="restore generated registry files from HEAD")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parent.parent).resolve()
    config_path = (args.config or repo_root / "mirror.yaml").resolve()
    if args.restore:
        return cmd_restore(repo_root)
    return cmd_apply(config_path, repo_root, args.dry_run)


# Compatibility helpers retained for external callers of the original script.
def load_mirrors(config_path: Path) -> list[Mirror]:
    return load_config(config_path).mirrors if config_path.is_file() else []


def load_github_release_prefix(config_path: Path) -> str:
    return load_config(config_path).github_url_prefix if config_path.is_file() else ""


def compute_diffs(lines: list[str], mirrors: list[Mirror]) -> list[LineDiff]:
    result: list[LineDiff] = []
    pattern = re.compile(r"^(?P<indent>\s+url:\s+)(?P<q>[\"']?)(?P<url>https?://[^\s\"']*)(?P=q)\s*$")
    for lineno, line in enumerate(lines, 1):
        match = pattern.match(line.rstrip("\r\n"))
        if not match:
            continue
        rewritten = _apply_mirrors(match.group("url"), mirrors)
        if rewritten != match.group("url"):
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            quote = match.group("q")
            result.append(LineDiff(lineno, line, f"{match.group('indent')}{quote}{rewritten}{quote}{ending}"))
    return result


def inject_github_release_urls(content: str, prefix: str, owner: str, repo: str) -> str:
    del owner, repo
    return process_content(content, Config(github_url_prefix=prefix))


def apply_to_file(path: Path, mirrors: list[Mirror], gh_prefix: str, dry_run: bool, repo_root: Path) -> bool:
    return apply_result(process_file(path, Config(mirrors, gh_prefix)), dry_run, repo_root)


if __name__ == "__main__":
    sys.exit(main())

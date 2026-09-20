#!/usr/bin/env python3
"""Validate generated aqua Registry output before publication."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml

from mirror import ProjectionError, find_registry_files, load_config, process_content


YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
DIRECT_GITHUB_DOWNLOAD_PREFIXES = (
    "https://github.com/",
    "https://raw.githubusercontent.com/",
)


class ValidationError(ValueError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=YAML_LOADER)
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"{path}: cannot load YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: document root must be a mapping")
    return value


def downloadable_urls(value: Any, *, key: str | None = None) -> Iterable[str]:
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from downloadable_urls(child, key=str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from downloadable_urls(child, key=key)
    elif isinstance(value, str) and key in {"url", "opts"}:
        yield value


def package_counter(documents: Iterable[dict[str, Any]]) -> Counter[str]:
    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): normalize(child) for key, child in value.items()}
        if isinstance(value, list):
            return [normalize(child) for child in value]
        return value

    result: Counter[str] = Counter()
    for document in documents:
        packages = document.get("packages")
        if not isinstance(packages, list):
            raise ValidationError("registry document is missing a packages list")
        result.update(json.dumps(normalize(package), ensure_ascii=False, sort_keys=True) for package in packages)
    return result


def validate(repo_root: Path, schema_path: Path) -> tuple[int, int]:
    config = load_config(repo_root / "mirror.yaml")
    package_paths = find_registry_files(repo_root)
    aggregate_path = repo_root / "registry.yaml"
    package_documents: list[dict[str, Any]] = []

    for path in package_paths:
        content = path.read_text(encoding="utf-8")
        try:
            projected = process_content(content, config, str(path))
        except ProjectionError as exc:
            raise ValidationError(str(exc)) from exc
        if projected != content:
            raise ValidationError(f"{path}: mirror projection is not idempotent")
        document = load_yaml(path)
        direct = [url for url in downloadable_urls(document) if url.startswith(DIRECT_GITHUB_DOWNLOAD_PREFIXES)]
        if direct:
            raise ValidationError(f"{path}: direct GitHub download remains: {direct[0]}")
        package_documents.append(document)

    aggregate = load_yaml(aggregate_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(aggregate)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path)
        raise ValidationError(f"{aggregate_path}:{location}: schema validation failed: {exc.message}") from exc

    expected = package_counter(package_documents)
    actual = package_counter([aggregate])
    if actual != expected:
        missing = sum((expected - actual).values())
        unexpected = sum((actual - expected).values())
        raise ValidationError(
            f"{aggregate_path}: aggregate differs from package sources "
            f"({missing} missing, {unexpected} unexpected package definitions)"
        )

    return len(package_paths), sum(expected.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a projected aqua Registry.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parent.parent / ".ai" / "aqua" / "json-schema" / "registry.json",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        file_count, package_count = validate(args.repo_root.resolve(), args.schema.resolve())
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {package_count} package definitions from {file_count} package registry files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

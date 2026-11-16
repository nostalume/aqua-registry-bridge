from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from validate import ValidationError, main, validate


REGISTRY_SOURCE = textwrap.dedent(
    """\
    packages:
      - type: http
        name: owner/tool
        url: https://mirror.example/tool
    """
)


def schema_allowing(*keys: str) -> dict:
    properties = {key: {"type": "string"} for key in keys}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "packages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                },
            }
        },
    }


class TestSchemaDriftHint(unittest.TestCase):
    def run_validate(self, schema: dict, root: Path) -> None:
        (root / "pkgs" / "owner" / "tool").mkdir(parents=True)
        for path in (root / "pkgs" / "owner" / "tool" / "registry.yaml", root / "registry.yaml"):
            path.write_text(REGISTRY_SOURCE, encoding="utf-8")
        (root / "mirror.yaml").write_text("mirrors: []\n", encoding="utf-8")
        schema_path = root / "registry-schema.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        validate(root, schema_path)

    def test_unknown_field_points_at_the_aqua_version_pin(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            with self.assertRaises(ValidationError) as caught:
                self.run_validate(schema_allowing("type", "name"), Path(raw_tmp))

            message = str(caught.exception)

        self.assertIn("Additional properties are not allowed", message)
        self.assertIn("'url' was unexpected", message)
        self.assertIn("packages/0", message)
        self.assertIn("AQUA_VERSION", message)

    def test_other_schema_violations_keep_their_own_diagnosis(self) -> None:
        schema = schema_allowing("type", "name")
        schema["properties"]["packages"]["items"]["properties"]["url"] = {"type": "integer"}

        with tempfile.TemporaryDirectory() as raw_tmp:
            with self.assertRaises(ValidationError) as caught:
                self.run_validate(schema, Path(raw_tmp))

            message = str(caught.exception)

        self.assertIn("is not of type", message)
        self.assertNotIn("AQUA_VERSION", message)


GITHUB_PACKAGE = textwrap.dedent(
    """\
    packages:
      - type: github_release
        repo_owner: owner
        repo_name: tool
        asset: tool.tar.gz
    """
)


def build_repository(
    root: Path,
    *,
    package: str = REGISTRY_SOURCE,
    aggregate: str | None = None,
    config: str = "mirrors: []\n",
) -> Path:
    package_dir = root / "pkgs" / "owner" / "tool"
    package_dir.mkdir(parents=True)
    (package_dir / "registry.yaml").write_text(package, encoding="utf-8")
    (root / "registry.yaml").write_text(
        package if aggregate is None else aggregate, encoding="utf-8"
    )
    (root / "mirror.yaml").write_text(config, encoding="utf-8")
    schema_path = root / "registry-schema.json"
    schema_path.write_text(
        json.dumps(schema_allowing("type", "name", "url", "repo_owner", "repo_name", "asset")),
        encoding="utf-8",
    )
    return schema_path


class TestRegistryGates(unittest.TestCase):
    def check(self, **changes: object) -> str:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            schema_path = build_repository(root, **changes)
            with self.assertRaises(ValidationError) as caught:
                validate(root, schema_path)
            return str(caught.exception)

    def test_matching_snapshot_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            schema_path = build_repository(root)
            self.assertEqual(validate(root, schema_path), (1, 1))

    def test_command_reports_validated_counts(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            schema_path = build_repository(root)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = main(["--repo-root", str(root), "--schema", str(schema_path)])

        self.assertEqual(result, 0)
        self.assertIn("Validated 1 package definition", output.getvalue())

    def test_command_reports_validation_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            schema_path = build_repository(root, aggregate="packages: []\n")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                result = main(["--repo-root", str(root), "--schema", str(schema_path)])

        self.assertEqual(result, 1)
        self.assertIn("aggregate differs", errors.getvalue())

    def test_direct_github_download_is_rejected(self) -> None:
        message = self.check(package=REGISTRY_SOURCE.replace("mirror.example", "github.com"))
        self.assertIn("direct GitHub download remains", message)

    def test_unprojected_package_is_not_idempotent(self) -> None:
        message = self.check(
            package=GITHUB_PACKAGE,
            aggregate=REGISTRY_SOURCE,
            config="github_url_prefix: https://proxy.example\n",
        )
        self.assertIn("not idempotent", message)

    def test_package_document_that_is_not_a_mapping_is_rejected(self) -> None:
        message = self.check(package="- packages: []\n")
        self.assertIn("registry root must be a mapping", message)

    def test_aggregate_document_that_is_not_a_mapping_is_rejected(self) -> None:
        message = self.check(aggregate="- packages: []\n")
        self.assertIn("document root must be a mapping", message)

    def test_aggregate_without_packages_is_rejected(self) -> None:
        message = self.check(aggregate="registries: []\n")
        self.assertIn("missing a packages list", message)

    def test_unreadable_aggregate_reports_its_own_error(self) -> None:
        message = self.check(aggregate="packages: [\n")
        self.assertIn("cannot load YAML", message)

    def test_missing_package_in_aggregate_is_counted(self) -> None:
        message = self.check(aggregate="packages: []\n")
        self.assertIn("1 missing, 0 unexpected", message)

    def test_extra_package_in_aggregate_is_counted(self) -> None:
        extra = "  - type: http\n    name: owner/extra\n    url: https://mirror.example/extra\n"
        message = self.check(aggregate=REGISTRY_SOURCE + extra)
        self.assertIn("0 missing, 1 unexpected", message)


if __name__ == "__main__":
    unittest.main()

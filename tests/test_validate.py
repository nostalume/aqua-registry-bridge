from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from validate import ValidationError, validate


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
        schema_path.write_text(__import__("json").dumps(schema), encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from mirror import Config, Mirror, ProjectionError, find_registry_files, load_config, main, process_content


class TemporaryRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write(self, relative: str, content: str, *, newline: str | None = None) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8", newline=newline)
        return path


class TestConfig(TemporaryRepository):
    def test_loads_legacy_prefix_and_ignores_identity_mappings(self) -> None:
        path = self.write(
            "mirror.yaml",
            """\
            github_release_url_prefix: https://proxy.example/
            mirrors:
              - original: https://same.example/
                mirror: https://same.example/
              - original: https://origin.example/
                mirror: https://mirror.example/
            """,
        )

        config = load_config(path)

        self.assertEqual(config.github_url_prefix, "https://proxy.example")
        self.assertEqual(config.github_url_mode, "full_url")
        self.assertEqual(config.mirrors, [Mirror("https://origin.example/", "https://mirror.example/")])

    def test_new_prefix_takes_precedence(self) -> None:
        path = self.write(
            "mirror.yaml",
            """\
            github_url_prefix: https://new.example
            github_url_mode: host_path
            github_release_url_prefix: https://legacy.example
            """,
        )
        self.assertEqual(load_config(path).github_url_prefix, "https://new.example")
        self.assertEqual(load_config(path).github_url_mode, "host_path")

    def test_rejects_unknown_github_url_mode(self) -> None:
        path = self.write("mirror.yaml", "github_url_mode: opaque\n")
        with self.assertRaisesRegex(ProjectionError, "must be host_path or full_url"):
            load_config(path)


class TestFormattingAndFailures(unittest.TestCase):
    def test_crlf_and_quotes_are_preserved(self) -> None:
        source = (
            "# comment\r\n"
            "packages:\r\n"
            "  - type: http\r\n"
            "    url: 'https://origin.example/{{.Version}}'\r\n"
        )
        result = process_content(
            source,
            Config(mirrors=[Mirror("https://origin.example/", "https://mirror.example/")]),
        )
        self.assertNotIn("\n", result.replace("\r\n", ""))
        self.assertIn("url: 'https://mirror.example/{{.Version}}'", result)
        self.assertIn("# comment", result)

    def test_malformed_yaml_has_source_context(self) -> None:
        with self.assertRaisesRegex(ProjectionError, "broken.yaml: invalid YAML"):
            process_content("packages: [", Config(), "broken.yaml")

    def test_scalar_urls_in_cosign_options_are_rewritten(self) -> None:
        source = textwrap.dedent(
            """\
            packages:
              - type: http
                name: example/tool
                url: https://downloads.example/tool
                cosign:
                  opts:
                    - --signature
                    - https://github.com/example/tool/releases/download/{{.Version}}/tool.sig
            """
        )
        result = process_content(
            source,
            Config(mirrors=[Mirror("https://github.com/", "https://proxy.example/https://github.com/")]),
        )
        self.assertIn(
            "https://proxy.example/https://github.com/example/tool/releases/download/{{.Version}}/tool.sig",
            result,
        )


class TestCommandBoundary(TemporaryRepository):
    def setUp(self) -> None:
        super().setUp()
        self.config = self.write(
            "mirror.yaml",
            """\
            mirrors:
              - original: https://origin.example/
                mirror: https://mirror.example/
            """,
        )

    def test_only_package_registry_files_are_owned(self) -> None:
        package = self.write("pkgs/a/b/registry.yaml", "packages: []\n")
        root_registry = self.write("registry.yaml", "packages: []\n")
        self.write("pkgs/a/b/other.yaml", "packages: []\n")

        self.assertEqual(find_registry_files(self.root), [package])
        self.assertNotIn(root_registry, find_registry_files(self.root))

    def test_dry_run_reports_without_writing(self) -> None:
        package = self.write(
            "pkgs/a/b/registry.yaml",
            """\
            packages:
              - type: http
                name: a/b
                url: https://origin.example/tool
            """,
        )
        original = package.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()):
            result = main(["--repo-root", str(self.root), "--dry-run"])

        self.assertEqual(result, 0)
        self.assertEqual(package.read_bytes(), original)

    def test_invalid_file_prevents_all_writes(self) -> None:
        valid = self.write(
            "pkgs/a/valid/registry.yaml",
            """\
            packages:
              - type: http
                name: a/valid
                url: https://origin.example/tool
            """,
        )
        self.write("pkgs/z/invalid/registry.yaml", "packages: [\n")
        original = valid.read_bytes()

        with contextlib.redirect_stderr(io.StringIO()):
            result = main(["--repo-root", str(self.root)])

        self.assertEqual(result, 1)
        self.assertEqual(valid.read_bytes(), original)

    def test_missing_config_is_a_normal_command_error(self) -> None:
        self.config.unlink()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--repo-root", str(self.root)]), 1)

    def test_invalid_config_is_a_normal_command_error(self) -> None:
        self.config.write_text("github_url_mode: opaque\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--repo-root", str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()

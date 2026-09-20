from __future__ import annotations

import io
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from mirror import Config, Mirror, main, process_content


class TestGitHubProjection(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = Config(github_url_prefix="https://proxy.example")

    def transform(self, source: str) -> str:
        return process_content(textwrap.dedent(source), self.cfg)

    def test_projects_release_base_and_version_override_to_http(self) -> None:
        result = self.transform(
            """\
            packages:
              - type: github_release
                repo_owner: cli
                repo_name: cli
                asset: gh_{{.Version}}_{{.OS}}_{{.Arch}}.tar.gz
                version_overrides:
                  - version_constraint: semver("< 2.0.0")
                    asset: old-gh_{{.Version}}.zip
            """
        )

        self.assertEqual(result.count("type: http"), 2)
        self.assertIn(
            "url: https://proxy.example/github.com/cli/cli/releases/download/"
            "{{.Version}}/gh_{{.Version}}_{{.OS}}_{{.Arch}}.tar.gz",
            result,
        )
        self.assertIn("{{.Version}}/old-gh_{{.Version}}.zip", result)

    def test_projects_each_package_with_its_own_identity(self) -> None:
        result = self.transform(
            """\
            packages:
              - type: github_release
                repo_owner: first
                repo_name: one
                asset: one.tar.gz
              - type: github_release
                repo_owner: second
                repo_name: two
                asset: two.tar.gz
            """
        )

        self.assertIn("proxy.example/github.com/first/one/releases/download/{{.Version}}/one.tar.gz", result)
        self.assertIn("proxy.example/github.com/second/two/releases/download/{{.Version}}/two.tar.gz", result)
        self.assertNotIn("proxy.example/github.com/first/one/releases/download/{{.Version}}/two.tar.gz", result)

    def test_projects_archive_content_and_verification_downloads(self) -> None:
        result = self.transform(
            """\
            packages:
              - type: github_archive
                repo_owner: owner
                repo_name: source
              - type: github_content
                repo_owner: owner
                repo_name: content
                path: bin/tool-{{.OS}}-{{.Arch}}
              - type: github_release
                repo_owner: owner
                repo_name: signed
                asset: tool.tar.gz
                checksum:
                  type: github_release
                  asset: checksums.txt
                cosign:
                  signature:
                    type: github_release
                    asset: checksums.txt.sig
            """
        )

        self.assertEqual(result.count("type: http"), 5)
        self.assertIn("proxy.example/github.com/owner/source/archive/{{.Version}}.tar.gz", result)
        self.assertIn("proxy.example/raw.githubusercontent.com/owner/content/{{.Version}}/bin/tool-{{.OS}}-{{.Arch}}", result)
        self.assertIn("{{.Version}}/checksums.txt", result)
        self.assertIn("{{.Version}}/checksums.txt.sig", result)

    def test_inherited_checksum_follows_overridden_asset_url(self) -> None:
        result = self.transform(
            """\
            packages:
              - type: github_release
                repo_owner: owner
                repo_name: tool
                asset: tool-{{.Version}}.tar.gz
                checksum:
                  type: github_release
                  asset: "{{.Asset}}.sha256"
                version_overrides:
                  - version_constraint: semver("< 2.0.0")
                    asset: old-tool-{{.Version}}.zip
            """
        )

        self.assertIn('url: "{{.AssetURL}}.sha256"', result)
        self.assertNotIn("tool-{{.Version}}.tar.gz.sha256", result)
        self.assertIsInstance(__import__("yaml").safe_load(result), dict)

    def test_rewrites_existing_http_url_without_reformatting_yaml(self) -> None:
        cfg = Config(
            mirrors=[Mirror("https://nodejs.org/dist/", "https://mirror.example/node/")]
        )
        source = textwrap.dedent(
            """\
            # retained comment
            packages:
              - type: http
                url: 'https://nodejs.org/dist/{{.Version}}/node.tar.gz'
            """
        )

        result = process_content(source, cfg)

        self.assertIn("# retained comment", result)
        self.assertIn("url: 'https://mirror.example/node/{{.Version}}/node.tar.gz'", result)

    def test_projection_is_byte_idempotent(self) -> None:
        source = textwrap.dedent(
            """\
            packages:
              - type: github_release
                repo_owner: cli
                repo_name: cli
                asset: gh.tar.gz
            """
        )
        once = process_content(source, self.cfg)
        self.assertEqual(process_content(once, self.cfg), once)

    def test_insertion_after_block_version_constraint_remains_valid_yaml(self) -> None:
        source = textwrap.dedent(
            """\
            packages:
              - type: github_release
                repo_owner: owner
                repo_name: tool
                version_constraint: "false"
                version_overrides:
                  - version_constraint: >-
                      semver(">= 1.0.0") &&
                      semver("< 2.0.0")
                    asset: tool-{{.Version}}.tar.gz
            """
        )

        result = process_content(source, self.cfg)

        self.assertIn("type: http", result)
        self.assertIsInstance(__import__("yaml").safe_load(result), dict)

    def test_yaml_alias_is_projected_once(self) -> None:
        source = textwrap.dedent(
            """\
            packages:
              - type: github_release
                repo_owner: owner
                repo_name: tool
                version_constraint: "false"
                version_overrides:
                  - version_constraint: semver(">= 1.0.0")
                    overrides: &shared
                      - goos: windows
                        asset: tool.exe
                  - version_constraint: "true"
                    overrides: *shared
            """
        )

        result = process_content(source, self.cfg)

        self.assertEqual(result.count("type: http"), 1)
        self.assertIsInstance(__import__("yaml").safe_load(result), dict)

    def test_private_github_package_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "private GitHub package"):
            self.transform(
                """\
                packages:
                  - type: github_release
                    repo_owner: private
                    repo_name: tool
                    private: true
                    asset: tool.tar.gz
                """
            )


class TestRepositoryBoundary(unittest.TestCase):
    def test_main_uses_explicit_repository_root_and_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            registry = root / "pkgs" / "例" / "工具" / "registry.yaml"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                "packages:\n"
                "  - type: http\n"
                "    name: 例/工具\n"
                "    description: 中文说明\n"
                "    url: https://nodejs.org/dist/tool\n",
                encoding="utf-8",
            )
            (root / "mirror.yaml").write_text(
                "mirrors:\n"
                "  - original: https://nodejs.org/dist/\n"
                "    mirror: https://mirror.example/node/\n",
                encoding="utf-8",
            )

            with mock.patch("sys.stdout", new_callable=io.StringIO):
                rc = main(["--repo-root", str(root)])

            self.assertEqual(rc, 0)
            self.assertIn("中文说明", registry.read_text(encoding="utf-8"))
            self.assertIn("https://mirror.example/node/tool", registry.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

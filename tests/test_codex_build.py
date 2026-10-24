import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('codex_build', Path(__file__).resolve().parents[1]/'codex/build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class CodexBuildTests(unittest.TestCase):
    def test_release_lock_normalization_changes_only_sourceless_workspace_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            root = source/'codex-rs'
            root.mkdir()
            (root/'Cargo.toml').write_text('[workspace.package]\nversion = "0.164.0"\n')
            external = '\n[[package]]\nname = "external"\nversion = "0.0.0"\nsource = "registry+https://example.invalid"\n'
            (root/'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "codex-tui"\nversion = "0.0.0"\n'+external)
            build.normalize_release_lock(source)
            result = (root/'Cargo.lock').read_text()
            self.assertIn('name = "codex-tui"\nversion = "0.164.0"', result)
            self.assertIn(external, result)
            build.normalize_release_lock(source)
            self.assertEqual((root/'Cargo.lock').read_text(), result)

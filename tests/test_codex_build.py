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


class CodexExportPatchTests(unittest.TestCase):
    def test_export_captures_tracked_changes_and_hashes_all_but_the_lock_file(self):
        spec = importlib.util.spec_from_file_location('codex_export_patch', Path(__file__).resolve().parents[1]/'codex/export_patch.py')
        export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export)
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            # HOME points at the sandbox so user git configuration (signing, hooks) stays out.
            env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
                       GIT_COMMITTER_EMAIL='t@x', HOME=temp, GIT_CONFIG_GLOBAL=os.devnull)
            def run(*args):
                subprocess.run(['git', *args], cwd=source, check=True, env=env, capture_output=True)
            run('init', '-q')
            (source/'codex-rs').mkdir()
            (source/'codex-rs'/'Cargo.lock').write_text('version = "0.0.0"\n')
            (source/'codex-rs'/'lib.rs').write_text('fn a() {}\n')
            run('add', '.')
            run('commit', '-q', '-m', 'pinned')
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, env=env, text=True).strip()
            (source/'codex-rs'/'Cargo.lock').write_text('version = "0.164.0"\n')
            (source/'codex-rs'/'lib.rs').write_text('fn a() {}\nfn b() {}\n')
            (source/'codex-rs'/'new.rs').write_text('fn c() {}\n')
            run('add', 'codex-rs/new.rs')
            with self.assertRaises(ValueError):
                export.export(source, {'revision': 'deadbeef'})
            patch, hashes = export.export(source, {'revision': revision})
            self.assertIn(b'+++ b/codex-rs/Cargo.lock', patch)
            self.assertIn(b'+fn b() {}', patch)
            self.assertIn(b'+fn c() {}', patch)
            self.assertEqual(sorted(hashes), ['codex-rs/lib.rs', 'codex-rs/new.rs'])
            self.assertEqual(hashes['codex-rs/new.rs'], build.sha(source/'codex-rs'/'new.rs'))

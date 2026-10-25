import importlib.util
import os
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
            (root/'Cargo.toml').write_text('[workspace.package]\nversion = "1.2.3"\n')
            external = '\n[[package]]\nname = "external"\nversion = "0.0.0"\nsource = "registry+https://example.invalid"\n'
            (root/'Cargo.lock').write_text('version = 4\n\n[[package]]\nname = "codex-tui"\nversion = "0.0.0"\n'+external)
            build.normalize_release_lock(source)
            result = (root/'Cargo.lock').read_text()
            self.assertIn('name = "codex-tui"\nversion = "1.2.3"', result)
            self.assertIn(external, result)
            build.normalize_release_lock(source)
            self.assertEqual((root/'Cargo.lock').read_text(), result)


    def test_versions_are_read_from_the_source_and_our_inputs(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            source, ours = Path(temp)/'source', Path(temp)/'ours'
            (source/'codex-rs').mkdir(parents=True)
            (source/'codex-rs/Cargo.toml').write_text('[workspace.package]\nversion = "7.8.9"\n')
            ours.mkdir()
            for name in build.RUNTIME:
                (ours/name).write_text('# '+name)
            metadata = {'patch_sha256': 'a'*64}
            with patch.object(build, 'ROOT', ours):
                self.assertEqual(build.upstream_version(source), '7.8.9')
                first = build.bundle_version(source, metadata)
                self.assertRegex(first, r'^7\.8\.9-statusline\.[0-9a-f]{12}$')
                self.assertEqual(build.bundle_version(source, metadata), first)
                self.assertNotEqual(build.bundle_version(source, {'patch_sha256': 'b'*64}), first)
                (ours/'launch_codex.py').write_text('# changed launcher')
                self.assertNotEqual(build.bundle_version(source, metadata), first)
            (source/'codex-rs/Cargo.toml').write_text('[package]\nname = "x"\n')
            with self.assertRaisesRegex(ValueError, 'workspace version'):
                build.upstream_version(source)

    def test_package_drives_the_upstream_packager_and_yields_an_installable_bundle(self):
        from unittest.mock import patch
        import install_codex
        # Stand-in for upstream's scripts/build_codex_package.py with the same environment contract.
        packager = '''import argparse, json, os, sys
from pathlib import Path
if Path(os.environ.get("CODEX_REPO_ROOT", "/nonexistent")).resolve() != Path.cwd().resolve():
    sys.exit("CODEX_REPO_ROOT must point to the repository root")
parser = argparse.ArgumentParser()
for flag in ["--variant", "--package-version", "--package-dir", "--cargo-profile"]:
    parser.add_argument(flag, required=True)
args = parser.parse_args()
out = Path(args.package_dir)
(out/"bin").mkdir(parents=True)
(out/"bin/codex").write_text("#!/bin/sh\\n")
(out/"bin/codex").chmod(0o755)
(out/"codex-package.json").write_text(json.dumps({"version": args.package_version, "entrypoint": "bin/codex"}))
if os.environ.get("TOUCH_LOCK"):
    Path("codex-rs/Cargo.lock").write_text("changed")
'''
        with tempfile.TemporaryDirectory() as temp:
            source, ours = Path(temp)/'source', Path(temp)/'ours'
            (source/'codex-rs').mkdir(parents=True)
            (source/'scripts').mkdir()
            (source/'codex-rs/Cargo.toml').write_text('[workspace.package]\nversion = "7.8.9"\n')
            (source/'codex-rs/Cargo.lock').write_text('version = 4\n')
            (source/'scripts/build_codex_package.py').write_text(packager)
            (ours/'codex').mkdir(parents=True)
            for name in [*build.RUNTIME, 'codex/UPSTREAM-LICENSE', 'codex/UPSTREAM-NOTICE']:
                (ours/name).write_text('# '+name)
            metadata = {'revision': 'f'*40, 'patch_sha256': 'a'*64}
            with patch.object(build, 'ROOT', ours):
                bundle = build.package(source, Path(temp)/'bundle', metadata, 'dev')
                manifest = install_codex.verify(bundle)
                self.assertEqual(manifest['upstream_version'], '7.8.9')
                self.assertEqual(manifest['version'], build.bundle_version(source, metadata))
                self.assertEqual(manifest['entrypoint'], 'bin/codex')
                if os.name == 'posix':  # Windows marks files executable by extension, not mode bits
                    self.assertEqual(manifest['executables'], ['bin/codex'])
                with patch.dict('os.environ', TOUCH_LOCK='1'), self.assertRaisesRegex(ValueError, 'Cargo.lock'):
                    build.package(source, Path(temp)/'second', metadata, 'dev')
                self.assertFalse((Path(temp)/'second').exists())


class CodexExportPatchTests(unittest.TestCase):
    def test_export_captures_tracked_changes_and_hashes_all_but_the_lock_file(self):
        spec = importlib.util.spec_from_file_location('codex_export_patch', Path(__file__).resolve().parents[1]/'codex/export_patch.py')
        export = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(export)
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
            (source/'codex-rs'/'Cargo.lock').write_text('version = "1.2.3"\n')
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

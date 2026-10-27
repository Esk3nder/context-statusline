import hashlib
import json
import os
import platform
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from install_codex import RUNTIME, install, next_steps, rollback, uninstall


class InstallCodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / 'user prefix with spaces'
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.make_bundle('1.2.3-statusline.1')
        stock = self.prefix / 'bin/codex'
        stock.parent.mkdir(parents=True)
        stock.write_text('STOCK_CODEX')

    def make_bundle(self, version):
        # Layout names here are arbitrary: upstream's packager owns and validates the real ones.
        entrypoint = 'bin/codex' + ('.exe' if os.name == 'nt' else '')
        package = {'version': version, 'entrypoint': entrypoint, 'layoutVersion': 99}
        files = {entrypoint: b'#!/bin/sh\necho codex-test\n', 'deep/nested/resource/dir/helper': b'helper',
                 'codex-package.json': json.dumps(package).encode(),
                 **{name: b'# runtime\n' for name in RUNTIME}}
        for name, data in files.items():
            (self.bundle/name).parent.mkdir(parents=True, exist_ok=True)
            (self.bundle/name).write_bytes(data)
        manifest = {'version': version, 'entrypoint': entrypoint, 'upstream_version': '1.2.3',
                    'executables': [entrypoint, 'deep/nested/resource/dir/helper'],
                    'platform': platform.system().lower()+'-'+platform.machine().lower(),
                    'files': {name: hashlib.sha256(data).hexdigest() for name,data in files.items()}}
        (self.bundle/'manifest.json').write_text(json.dumps(manifest))

    def mutate_manifest(self, change):
        path = self.bundle/'manifest.json'
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))

    def test_wrong_os_or_architecture_is_rejected_before_activation(self):
        for target in ['other-arm64', platform.system().lower()+'-wrongarch']:
            with self.subTest(target=target):
                self.make_bundle('1.2.3-statusline.1')
                self.mutate_manifest(lambda value: value.update(platform=target))
                with self.assertRaisesRegex(ValueError, 'platform'):
                    install(self.bundle, self.prefix)
                self.assertFalse((self.prefix/'lib/context-statusline').exists())

    def test_inconsistent_canonical_metadata_is_rejected(self):
        for field, bad in [('version', 'other'), ('entrypoint', 'codex')]:
            with self.subTest(field=field):
                self.make_bundle('1.2.3-statusline.1')
                path = self.bundle/'codex-package.json'
                package = json.loads(path.read_text())
                package[field] = bad
                path.write_text(json.dumps(package))
                self.mutate_manifest(lambda value: value['files'].update({'codex-package.json': hashlib.sha256(path.read_bytes()).hexdigest()}))
                with self.assertRaisesRegex(ValueError, 'package'):
                    install(self.bundle, self.prefix)

    def test_missing_runtime_files_are_rejected(self):
        for name in sorted(RUNTIME | {'codex-package.json'}):
            with self.subTest(name=name):
                self.make_bundle('1.2.3-statusline.1')
                self.mutate_manifest(lambda value: value['files'].pop(name))
                with self.assertRaisesRegex(ValueError, 'runtime'):
                    install(self.bundle, self.prefix)

    def test_executables_come_from_the_manifest_and_must_be_listed(self):
        launcher = install(self.bundle, self.prefix)
        installed = launcher.parent.parent/'lib/context-statusline/versions/1.2.3-statusline.1'
        if os.name == 'posix':
            self.assertTrue(os.access(installed/'deep/nested/resource/dir/helper', os.X_OK))
            self.assertFalse(os.access(installed/'launch_codex.py', os.X_OK))
        for change, message in [(lambda value: value.pop('executables'), 'predates executable metadata'),
                                (lambda value: value.update(executables=['missing']), 'Invalid bundle manifest')]:
            with self.subTest(message=message):
                self.make_bundle('1.2.3-statusline.2')
                self.mutate_manifest(change)
                with self.assertRaisesRegex(ValueError, message):
                    install(self.bundle, self.prefix)

    def test_bundles_installed_before_executable_metadata_remain_rollback_targets(self):
        install(self.bundle, self.prefix)
        old = self.prefix/'lib/context-statusline/versions/1.2.3-statusline.1/manifest.json'
        value = json.loads(old.read_text())
        value.pop('executables')
        old.write_text(json.dumps(value))
        self.make_bundle('1.2.3-statusline.2')
        install(self.bundle, self.prefix)
        self.assertIn('1.2.3-statusline.1', rollback(self.prefix).read_text())

    def test_install_uses_verified_immutable_bundle_and_preserves_stock(self):
        launcher = install(self.bundle, self.prefix)
        self.assertEqual(launcher, self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline'))
        self.assertIn('launch_codex.py', launcher.read_text())
        self.assertIn('user prefix with spaces', launcher.read_text())
        self.assertEqual((self.prefix/'bin/codex').read_text(), 'STOCK_CODEX')
        self.assertEqual(install(self.bundle, self.prefix), launcher)

    def test_tampering_and_symlink_do_not_activate_or_overwrite(self):
        for mode in ['contents', 'symlink']:
            self.make_bundle('1.2.3-statusline.1')
            binary = self.bundle/'bin'/('codex.exe' if os.name == 'nt' else 'codex')
            if mode == 'contents': binary.write_text('TAMPERED')
            else:
                binary.unlink()
                binary.symlink_to(self.prefix/'bin/codex')
            with self.assertRaises(ValueError): install(self.bundle, self.prefix)
            self.assertFalse((self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).exists())
            if binary.is_symlink(): binary.unlink()

    def test_manifest_traversal_and_missing_runtime_are_rejected(self):
        path = self.bundle/'manifest.json'
        for invalid in [{'../escape': 'x'}, {'codex': '0'*64}]:
            path.write_text(json.dumps({'version': 'v1', 'files': invalid}))
            with self.assertRaises(ValueError): install(self.bundle, self.prefix)

    def test_upgrade_rollback_and_uninstall_leave_stock_and_other_files(self):
        install(self.bundle, self.prefix)
        self.make_bundle('1.2.3-statusline.2')
        install(self.bundle, self.prefix)
        rollback(self.prefix)
        self.assertIn('1.2.3-statusline.1', (self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).read_text())
        uninstall(self.prefix)
        self.assertFalse((self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).exists())
        self.assertEqual((self.prefix/'bin/codex').read_text(), 'STOCK_CODEX')

    def test_nested_package_layout_is_verified_and_installed(self):
        install(self.bundle, self.prefix)
        installed = self.prefix/'lib/context-statusline/versions/1.2.3-statusline.1'
        self.assertTrue((installed/'bin'/('codex.exe' if os.name == 'nt' else 'codex')).is_file())
        self.assertTrue((installed/'deep/nested/resource/dir/helper').is_file())

    def test_next_steps_name_the_missing_path_entry(self):
        launcher = install(self.bundle, self.prefix)
        with patch.dict(os.environ, {'PATH': os.defpath}):
            steps = next_steps(self.prefix)
        self.assertTrue(any(str(launcher.parent) in step and 'PATH' in step for step in steps), steps)
        with patch.dict(os.environ, {'PATH': str(launcher.parent)+os.pathsep+os.defpath}), \
             patch.object(sys, 'platform', 'linux'):
            self.assertEqual(next_steps(self.prefix), [])

    def test_existing_unowned_launcher_is_never_replaced(self):
        (self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).write_text('USER_TOOL')
        with self.assertRaises(ValueError): install(self.bundle, self.prefix)
        self.assertEqual((self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).read_text(), 'USER_TOOL')

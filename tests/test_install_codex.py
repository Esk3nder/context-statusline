import hashlib
import json
import os
import platform
from pathlib import Path
import tempfile
import unittest

from install_codex import install, rollback, uninstall


class InstallCodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / 'user prefix with spaces'
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.make_bundle('0.164.0-statusline.1')
        stock = self.prefix / 'bin/codex'
        stock.parent.mkdir(parents=True)
        stock.write_text('STOCK_CODEX')

    def make_bundle(self, version):
        suffix = '.exe' if os.name == 'nt' else ''
        system = platform.system().lower()
        arch = {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(platform.machine().lower(), platform.machine().lower())
        target = arch + {'darwin': '-apple-darwin', 'linux': '-unknown-linux-musl', 'windows': '-pc-windows-msvc'}[system]
        entrypoint = 'bin/codex' + suffix
        package = {'layoutVersion': 1, 'version': version, 'target': target, 'variant': 'codex',
                   'entrypoint': entrypoint, 'resourcesDir': 'codex-resources', 'pathDir': 'codex-path'}
        files = {entrypoint: b'#!/bin/sh\necho codex-test\n', 'bin/codex-code-mode-host'+suffix: b'helper',
                 'codex-path/rg'+suffix: b'rg', 'codex-package.json': json.dumps(package).encode(),
                 'codex_statusline.py': b'# renderer\n', 'launch_codex.py': b'# launcher\n',
                 'context_statusline.py': b'# shared\n', 'activity.py': b'# activity\n', 'session_snapshot.py': b'# snapshots\n'}
        if system == 'linux': files['codex-resources/bwrap'] = b'bwrap'
        if system == 'windows':
            for helper in ['codex-command-runner.exe', 'codex-windows-sandbox-setup.exe']:
                files['codex-resources/'+helper] = b'helper'
        for name, data in files.items():
            (self.bundle/name).parent.mkdir(parents=True, exist_ok=True)
            (self.bundle/name).write_bytes(data)
        manifest = {'version': version, 'entrypoint': entrypoint,
                    'platform': system+'-'+platform.machine().lower(),
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
                self.make_bundle('0.164.0-statusline.1')
                self.mutate_manifest(lambda value: value.update(platform=target))
                with self.assertRaisesRegex(ValueError, 'platform'):
                    install(self.bundle, self.prefix)
                self.assertFalse((self.prefix/'lib/context-statusline').exists())

    def test_inconsistent_canonical_metadata_is_rejected(self):
        for field, bad in [('target', 'x86_64-other-os'), ('version', 'other'), ('entrypoint', 'codex'),
                           ('layoutVersion', 2), ('variant', 'other'), ('pathDir', 'other'), ('resourcesDir', 'other')]:
            with self.subTest(field=field):
                self.make_bundle('0.164.0-statusline.1')
                path = self.bundle/'codex-package.json'
                package = json.loads(path.read_text())
                package[field] = bad
                path.write_text(json.dumps(package))
                self.mutate_manifest(lambda value: value['files'].update({'codex-package.json': hashlib.sha256(path.read_bytes()).hexdigest()}))
                with self.assertRaisesRegex(ValueError, 'package'):
                    install(self.bundle, self.prefix)

    def test_missing_canonical_helpers_are_rejected(self):
        manifest = json.loads((self.bundle/'manifest.json').read_text())
        helpers = [name for name in manifest['files'] if name.startswith(('codex-path/', 'codex-resources/', 'bin/codex-code-mode'))]
        for helper in helpers:
            with self.subTest(helper=helper):
                self.make_bundle('0.164.0-statusline.1')
                self.mutate_manifest(lambda value: value['files'].pop(helper))
                with self.assertRaisesRegex(ValueError, 'runtime'):
                    install(self.bundle, self.prefix)

    def test_install_uses_verified_immutable_bundle_and_preserves_stock(self):
        launcher = install(self.bundle, self.prefix)
        self.assertEqual(launcher, self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline'))
        self.assertIn('launch_codex.py', launcher.read_text())
        self.assertIn('user prefix with spaces', launcher.read_text())
        self.assertEqual((self.prefix/'bin/codex').read_text(), 'STOCK_CODEX')
        self.assertEqual(install(self.bundle, self.prefix), launcher)

    def test_tampering_and_symlink_do_not_activate_or_overwrite(self):
        for mode in ['contents', 'symlink']:
            self.make_bundle('0.164.0-statusline.1')
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
        self.make_bundle('0.164.0-statusline.2')
        install(self.bundle, self.prefix)
        rollback(self.prefix)
        self.assertIn('0.164.0-statusline.1', (self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).read_text())
        uninstall(self.prefix)
        self.assertFalse((self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).exists())
        self.assertEqual((self.prefix/'bin/codex').read_text(), 'STOCK_CODEX')

    def test_canonical_nested_package_layout_is_verified_and_installed(self):
        binary = 'codex.exe' if os.name == 'nt' else 'codex'
        install(self.bundle, self.prefix)
        installed = self.prefix/'lib/context-statusline/versions/0.164.0-statusline.1'
        self.assertTrue((installed/'bin'/binary).is_file())

    def test_existing_unowned_launcher_is_never_replaced(self):
        (self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).write_text('USER_TOOL')
        with self.assertRaises(ValueError): install(self.bundle, self.prefix)
        self.assertEqual((self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).read_text(), 'USER_TOOL')

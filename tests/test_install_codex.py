import hashlib
import json
import os
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
        files = {('codex.exe' if os.name == 'nt' else 'codex'): b'#!/bin/sh\necho codex-test\n', 'codex_statusline.py': b'# renderer\n',
                 'launch_codex.py': b'# launcher\n', 'context_statusline.py': b'# shared\n',
                 'activity.py': b'# activity\n', 'session_snapshot.py': b'# snapshots\n'}
        for name, data in files.items():
            (self.bundle/name).write_bytes(data)
        manifest = {'version': version, 'files': {name: hashlib.sha256(data).hexdigest() for name,data in files.items()}}
        (self.bundle/'manifest.json').write_text(json.dumps(manifest))

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
            binary = self.bundle/('codex.exe' if os.name == 'nt' else 'codex')
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
        (self.bundle/'bin').mkdir()
        (self.bundle/binary).rename(self.bundle/'bin'/binary)
        manifest = json.loads((self.bundle/'manifest.json').read_text())
        manifest['entrypoint'] = 'bin/' + binary
        manifest['files']['bin/' + binary] = manifest['files'].pop(binary)
        (self.bundle/'manifest.json').write_text(json.dumps(manifest))
        install(self.bundle, self.prefix)
        installed = self.prefix/'lib/context-statusline/versions/0.164.0-statusline.1'
        self.assertTrue((installed/'bin'/binary).is_file())

    def test_existing_unowned_launcher_is_never_replaced(self):
        (self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).write_text('USER_TOOL')
        with self.assertRaises(ValueError): install(self.bundle, self.prefix)
        self.assertEqual((self.prefix/('bin/codex-statusline.cmd' if os.name == 'nt' else 'bin/codex-statusline')).read_text(), 'USER_TOOL')

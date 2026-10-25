import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from context_statusline import settings_fragment

ROOT = Path(__file__).resolve().parents[1]


class InstallClaudeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config = Path(temp.name)/'claude config'
        self.settings = self.config/'settings.json'
        self.env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.config))

    def run_installer(self, *args):
        return subprocess.run([sys.executable, str(ROOT/'install_claude.py'), *args],
                              env=self.env, capture_output=True, text=True)

    def read(self):
        return json.loads(self.settings.read_text())

    def test_fresh_install_writes_both_statuslines_without_hooks(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.settings))
        fragment = settings_fragment()
        self.assertEqual(self.read(), {'statusLine': fragment['statusLine'],
                                       'subagentStatusLine': fragment['subagentStatusLine']})
        self.assertEqual(list(self.config.glob('*.bak')), [], 'nothing to back up on a fresh install')

    def test_existing_settings_and_hooks_survive_and_are_backed_up(self):
        user_hook = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'my-guard'}]}
        self.config.mkdir()
        self.settings.write_text(json.dumps({'model': 'opus', 'hooks': {'PreToolUse': [user_hook]}}))
        self.settings.chmod(0o600)
        self.assertEqual(self.run_installer('--observers').returncode, 0)
        settings = self.read()
        self.assertEqual(settings['model'], 'opus')
        self.assertEqual(settings['hooks']['PreToolUse'][0], user_hook)
        self.assertEqual(set(settings['hooks']), set(settings_fragment()['hooks']))
        if os.name == 'posix':
            self.assertEqual(self.settings.stat().st_mode & 0o777, 0o600)
        [backup] = self.config.glob('settings.json.*.bak')
        self.assertEqual(json.loads(backup.read_text())['hooks']['PreToolUse'], [user_hook])

    def test_install_is_idempotent(self):
        self.run_installer('--observers')
        first = self.settings.read_text()
        result = self.run_installer('--observers')
        self.assertEqual(result.returncode, 0)
        self.assertIn('already has', result.stderr)
        self.assertEqual(self.settings.read_text(), first)
        self.assertEqual(len(self.read()['hooks']['PreToolUse']), 1)

    def test_another_tools_statusline_is_kept_unless_replace_is_given(self):
        self.config.mkdir()
        other = {'statusLine': {'type': 'command', 'command': 'other-tool'}}
        self.settings.write_text(json.dumps(other))
        result = self.run_installer()
        self.assertEqual(result.returncode, 1)
        self.assertIn('other-tool', result.stderr)
        self.assertIn('--replace', result.stderr)
        self.assertEqual(self.read(), other)
        self.assertEqual(self.run_installer('--replace').returncode, 0)
        self.assertEqual(self.read()['statusLine'], settings_fragment()['statusLine'])

    def test_dry_run_prints_a_diff_and_writes_nothing(self):
        result = self.run_installer('--observers', '--dry-run')
        self.assertEqual(result.returncode, 0)
        self.assertIn('+  "statusLine"', result.stdout)
        self.assertFalse(self.settings.exists())

    def test_uninstall_removes_only_what_this_checkout_added(self):
        user_hook = {'hooks': [{'type': 'command', 'command': 'my-guard'}]}
        self.config.mkdir()
        self.settings.write_text(json.dumps({'model': 'opus', 'hooks': {'PreToolUse': [user_hook]}}))
        self.run_installer('--observers')
        self.assertEqual(self.run_installer('--uninstall').returncode, 0)
        self.assertEqual(self.read(), {'model': 'opus', 'hooks': {'PreToolUse': [user_hook]}})

    def test_uninstall_without_settings_creates_nothing(self):
        result = self.run_installer('--uninstall')
        self.assertEqual(result.returncode, 0)
        self.assertFalse(self.settings.exists())

    def test_invalid_settings_are_never_rewritten(self):
        self.config.mkdir()
        for text in ['{not json', '[]', '{"hooks": []}']:
            with self.subTest(text=text):
                self.settings.write_text(text)
                result = self.run_installer('--observers')
                self.assertEqual(result.returncode, 1)
                self.assertIn('No change made', result.stderr)
                self.assertEqual(self.settings.read_text(), text)


if __name__ == '__main__':
    unittest.main()

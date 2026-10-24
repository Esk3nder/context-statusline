import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'tests/fixtures/subagents.json').read_text())


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / 'state'
        self.env = dict(os.environ, CONTEXT_STATUSLINE_STATE_DIR=str(self.state), NO_COLOR='1')
        self.payload = copy.deepcopy(BASE)
        for task in self.payload['tasks']:
            task['startTime'] = int((time.time() - 192) * 1000)

    def run_cli(self, mode, payload):
        return subprocess.run(['bash', str(ROOT / 'context-bar.sh'), '--plain', mode], input=json.dumps(payload),
                              text=True, capture_output=True, env=self.env, timeout=5)

    def hook(self, event, agent='agent-review', session='fixture-session', **extra):
        result = self.run_cli('--hook', dict(session_id=session, hook_event_name=event, agent_id=agent, **extra))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')  # An observer must never emit a hook decision.
        return result

    def rows(self, payload=None):
        result = self.run_cli('--subagents', payload or self.payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(row) for row in result.stdout.splitlines()]

    def test_native_jsonl_preserves_ids_and_reported_states(self):
        rows = self.rows()
        self.assertEqual([x['id'] for x in rows], ['agent-review', 'agent-research'])
        self.assertIn('reviewer', rows[0]['content'])
        self.assertIn('running', rows[0]['content'])
        self.assertIn('completed', rows[1]['content'])
        self.assertNotIn('success', rows[1]['content'])
        self.assertNotIn('▁', rows[0]['content'])

    def test_completion_duration_requires_an_observed_stop(self):
        before = self.rows()[1]['content']
        self.assertNotRegex(before, r'\d+m\d+s')
        self.hook('SubagentStop', agent='agent-research')
        after = self.rows()[1]['content']
        self.assertRegex(after, r'3m\d+s')

    def test_pending_tool_is_not_claimed_to_be_executing(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        text = self.rows()[0]['content']
        self.assertIn('last event', text)
        self.assertIn('tool result pending', text)
        self.assertNotIn('still running', text)
        self.assertNotIn('stalled', text)
        self.hook('PostToolUse', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('result pending', self.rows()[0]['content'])

    def test_pending_parallel_calls_are_correlated_by_id(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        self.hook('PreToolUse', tool_name='Read', tool_use_id='call-2')
        self.hook('PostToolUse', tool_name='Read', tool_use_id='call-2')
        self.assertIn('Bash', self.rows()[0]['content'])
        self.hook('PostToolUse', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('result pending', self.rows()[0]['content'])

    def test_unmatched_ids_do_not_get_someone_elses_activity(self):
        self.hook('PreToolUse', agent='different-id', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('last event', self.rows()[0]['content'])

    def test_sessions_are_isolated(self):
        self.hook('PreToolUse', session='other-session', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('last event', self.rows()[0]['content'])

    def test_permission_is_a_reported_event_not_a_permanent_waiting_claim(self):
        self.hook('PermissionRequest', tool_name='Bash')
        text = self.rows()[0]['content']
        self.assertIn('approval requested', text)
        self.assertNotIn('approval required', text)
        self.assertNotIn('tool result pending', text)

    def test_observer_does_not_persist_tool_inputs_results_or_summary(self):
        secret = 'SECRET_VALUE_SHOULD_NEVER_BE_STORED'
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1', tool_input={'command': secret})
        self.hook('PostToolUse', tool_name='Bash', tool_use_id='call-1', tool_response=secret)
        self.hook('PostCompact', compact_summary=secret)
        files = list(self.state.iterdir())
        self.assertTrue(files)
        self.assertTrue(all(secret.encode() not in p.read_bytes() for p in files if p.is_file()))
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.state / 'activity.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_cache_symlink_is_refused_without_writing_through_it(self):
        target = Path(self.temp.name) / 'target'
        target.mkdir()
        self.state.symlink_to(target, target_is_directory=True)
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        self.assertEqual(list(target.iterdir()), [])
        self.assertNotIn('last event', self.rows()[0]['content'])

    def test_session_end_clears_activity(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        self.hook('SessionEnd')
        self.assertNotIn('last event', self.rows()[0]['content'])

    def test_concurrent_events_do_not_drop_other_agents(self):
        # Initialize the database, then exercise real separate writer processes.
        self.hook('SubagentStart')
        def write(i):
            self.hook('PreToolUse', agent=f'agent-{i}', tool_name='Bash', tool_use_id=f'call-{i}')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(8)))
        payload = copy.deepcopy(self.payload)
        payload['tasks'] = [dict(self.payload['tasks'][0], id=f'agent-{i}') for i in range(8)]
        self.assertEqual(sum('result pending' in x['content'] for x in self.rows(payload)), 8)

    def test_expired_cache_is_not_shown(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        with sqlite3.connect(self.state / 'activity.sqlite3') as db:
            db.execute('UPDATE sessions SET updated_at = 1')
        self.assertNotIn('last event', self.rows()[0]['content'])

    def test_native_width_applies_to_every_content_line(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        for width in [12, 24, 44, 72]:
            payload = copy.deepcopy(self.payload)
            payload['columns'] = width
            for row in self.rows(payload):
                for line in row['content'].splitlines():
                    self.assertLessEqual(len(line), width)

    def test_unpaired_unicode_in_task_ids_remains_valid_jsonl(self):
        self.payload['tasks'][0]['id'] = '\ud800'
        self.assertEqual(self.rows()[0]['id'], '\ud800')

    def test_diagnostics_do_not_invent_forecasts(self):
        result = self.run_cli('--diagnostics', {'session_id': 'fixture-session'})
        self.assertEqual(result.returncode, 0, result.stderr)
        diagnostic = json.loads(result.stdout)
        self.assertIsNone(diagnostic['context_runway'])
        self.assertIsNone(diagnostic['quota_exhaustion'])

    def test_settings_fragment_contains_observer_only_commands(self):
        result = subprocess.run(['bash', str(ROOT / 'context-bar.sh'), '--settings'], text=True,
                                capture_output=True, env=self.env, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = json.loads(result.stdout)
        self.assertIn('statusLine', settings)
        self.assertIn('subagentStatusLine', settings)
        for groups in settings['hooks'].values():
            for group in groups:
                for hook in group['hooks']:
                    self.assertIn('--hook', hook['command'])
                    self.assertNotIn('decision', hook)

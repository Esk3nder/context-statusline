import copy
from contextlib import closing
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
        self.env = dict(os.environ, CONTEXT_STATUSLINE_STATE_DIR=str(self.state), NO_COLOR='1',
                        CLAUDE_CONFIG_DIR=str(Path(self.temp.name) / 'config'), CLAUDE_CODE_TASK_LIST_ID='')
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

    def cached_state(self):
        with closing(sqlite3.connect(self.state / 'activity.sqlite3')) as db:
            return json.loads(db.execute('SELECT body FROM sessions').fetchone()[0])

    def test_file_targets_keep_only_sanitized_basename(self):
        self.hook('PreToolUse', agent='@main', tool_name='Read', tool_use_id='read-1',
                  tool_input={'file_path': '/SECRET_PARENT/test\u202e_file.py', 'other': 'SECRET_PAYLOAD'})
        state = self.cached_state()
        call = next(iter(state['agents']['@main']['pending'].values()))
        self.assertEqual(call['target'], 'test _file.py')
        self.assertNotIn('SECRET', json.dumps(state))

    def test_successful_skill_and_mcp_calls_are_recorded_once(self):
        for _ in range(2):
            self.hook('PostToolUse', agent='@main', tool_name='Skill',
                      tool_input={'skill': 'brainstorming', 'args': 'SECRET_ARGS'}, tool_response='SECRET_RESULT')
        self.hook('PostToolUse', tool_name='mcp__context7__query_docs')
        self.hook('PostToolUseFailure', tool_name='mcp__failed_server__call')
        self.hook('PostToolUseFailure', tool_name='Skill', tool_input={'skill': 'failed-skill'})
        used = self.cached_state()['used']
        self.assertEqual(used, {'skills': ['brainstorming'], 'mcps': ['context7']})
        self.assertNotIn('SECRET', json.dumps(self.cached_state()))

    def test_legacy_todos_change_only_after_confirmed_success_and_stay_agent_scoped(self):
        todos = [{'content': 'Build the panel', 'status': 'in_progress', 'activeForm': 'SECRET_DETAIL'}]
        self.hook('PreToolUse', agent='@main', tool_name='TodoWrite', tool_use_id='todo-1', tool_input={'todos': todos})
        self.assertNotIn('todos', self.cached_state()['agents']['@main'])
        self.hook('PostToolUse', agent='@main', tool_name='TodoWrite', tool_use_id='todo-1', tool_input={'todos': todos})
        self.hook('PostToolUseFailure', agent='@main', tool_name='TodoWrite', tool_input={'todos': []})
        self.hook('PostToolUse', tool_name='TodoWrite', tool_input={'todos': [{'content': 'Child task', 'status': 'pending'}]})
        state = self.cached_state()
        self.assertEqual(state['agents']['@main']['todos'], [{'subject': 'Build the panel', 'status': 'in_progress'}])
        self.assertEqual(state['agents']['agent-review']['todos'][0]['subject'], 'Child task')
        self.assertNotIn('SECRET', json.dumps(state))
        self.hook('PostToolUse', agent='@main', tool_name='TodoWrite', tool_input={'todos': []})
        self.assertEqual(self.cached_state()['agents']['@main']['todos'], [])

    def test_stopping_agent_clears_target_and_pending_calls(self):
        self.hook('PreToolUse', tool_name='Edit', tool_use_id='call-1', tool_input={'file_path': '/tmp/test.py'})
        self.assertIn('target', next(iter(self.cached_state()['agents']['agent-review']['pending'].values())))
        self.hook('SubagentStop')
        self.assertEqual(self.cached_state()['agents']['agent-review']['pending'], {})

    def test_main_cli_reads_native_tasks_and_observed_targets_together(self):
        tasks = Path(self.env['CLAUDE_CONFIG_DIR']) / 'tasks/fixture-session'
        tasks.mkdir(parents=True)
        task = tasks / '1.json'
        task.write_text(json.dumps({'id': '1', 'subject': 'Native checklist item', 'status': 'in_progress'}))
        self.hook('PostToolUse', agent='@main', tool_name='TodoWrite',
                  tool_input={'todos': [{'content': 'Stale fallback', 'status': 'pending'}]})
        self.hook('PreToolUse', agent='@main', tool_name='Read', tool_use_id='read-1',
                  tool_input={'file_path': '/tmp/main.py'})
        payload = {'session_id': 'fixture-session', 'columns': 128}
        result = self.run_cli('--plain', payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Native checklist item', result.stdout)
        self.assertIn('Read main.py', result.stdout)
        self.assertNotIn('Stale fallback', result.stdout)
        task.unlink()
        self.assertNotIn('TASKS', self.run_cli('--plain', payload).stdout)

    def test_invalid_explicit_agent_identity_never_becomes_main_activity(self):
        self.hook('PreToolUse', agent='@main', tool_name='Read', tool_use_id='main-call',
                  tool_input={'file_path': '/tmp/main.py'})
        for invalid in [None, '', [], ['child'], 1, 'x' * 257, '\ud800']:
            self.hook('PreToolUse', agent=invalid, tool_name='Read', tool_use_id='child-call',
                      tool_input={'file_path': '/tmp/child.py'})
        pending = self.cached_state()['agents']['@main']['pending']
        self.assertEqual(len(pending), 1)
        self.assertEqual(next(iter(pending.values()))['target'], 'main.py')

    def test_absent_agent_identity_still_means_main(self):
        result = self.run_cli('--hook', {'session_id': 'fixture-session', 'hook_event_name': 'PreToolUse',
            'tool_name': 'Read', 'tool_use_id': 'main-call', 'tool_input': {'file_path': '/tmp/main.py'}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('@main', self.cached_state()['agents'])

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
        self.assertIn('Bash', text)
        self.assertIn('awaiting result', text)
        self.assertNotIn('still running', text)
        self.assertNotIn('stalled', text)
        self.hook('PostToolUse', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

    def test_pending_parallel_calls_are_correlated_by_id(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        self.hook('PreToolUse', tool_name='Read', tool_use_id='call-2')
        self.hook('PostToolUse', tool_name='Read', tool_use_id='call-2')
        self.assertIn('Bash', self.rows()[0]['content'])
        self.hook('PostToolUse', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

    def test_unmatched_ids_do_not_get_someone_elses_activity(self):
        self.hook('PreToolUse', agent='different-id', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

    def test_sessions_are_isolated(self):
        self.hook('PreToolUse', session='other-session', tool_name='Bash', tool_use_id='call-1')
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

    def test_permission_is_a_reported_event_not_a_permanent_waiting_claim(self):
        self.hook('PermissionRequest', tool_name='Bash')
        text = self.rows()[0]['content']
        self.assertIn('approval requested', text)
        self.assertNotIn('approval required', text)
        self.assertNotIn('awaiting result', text)

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
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

    def test_session_end_clears_activity(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        self.hook('SessionEnd')
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

    def test_concurrent_events_do_not_drop_other_agents(self):
        # Initialize the database, then exercise real separate writer processes.
        self.hook('SubagentStart')
        def write(i):
            self.hook('PreToolUse', agent=f'agent-{i}', tool_name='Bash', tool_use_id=f'call-{i}')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(8)))
        payload = copy.deepcopy(self.payload)
        payload['tasks'] = [dict(self.payload['tasks'][0], id=f'agent-{i}') for i in range(8)]
        self.assertEqual(sum('awaiting result' in x['content'] for x in self.rows(payload)), 8)

    def test_expired_cache_is_not_shown(self):
        self.hook('PreToolUse', tool_name='Bash', tool_use_id='call-1')
        with closing(sqlite3.connect(self.state / 'activity.sqlite3')) as db:
            db.execute('UPDATE sessions SET updated_at = 1')
            db.commit()
        self.assertNotIn('awaiting result', self.rows()[0]['content'])

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

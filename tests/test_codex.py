"""Codex snapshots never consume Claude state or arbitrary event bodies."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from codex_statusline import render_codex
from context_statusline import cell_width

NOW = 1800000000
PAYLOAD = {'schema_version': 1, 'host': 'codex', 'session_id': 'thread-1',
    'model': 'gpt-6-astra', 'effort': 'high', 'cwd': '/workspace/product',
    'context': {'used_tokens': 74000, 'window_tokens': 200000},
    'limits': [{'used_percent': 22, 'window_minutes': 300, 'resets_at': NOW + 7800}],
    'attached_ms': 723000, 'configuration': {'mcps': 6},
    'plan': [{'step': 'Inspect', 'status': 'completed'}, {'step': 'Build', 'status': 'inProgress'},
             {'step': 'Verify', 'status': 'pending'}],
    'tools': [{'id': 'call-1', 'tool': 'Read', 'target': '/tmp/main.py', 'at': NOW-3}],
    'agents': [{'id': 'child-1', 'role': 'reviewer', 'status': 'running'}]}


class CodexTests(unittest.TestCase):
    def render(self, payload=None, width=128, color=False):
        return render_codex(PAYLOAD if payload is None else payload, width, color, now=NOW)

    def test_native_metrics_plan_and_same_neutral_design(self):
        text = self.render()
        for value in ['37%', '126k left', '5H QUOTA USED', '22%', 'gpt-6-astra', 'high',
                      '12m3s attached', 'Inspect', 'Build', 'Verify', '6 MCPs configured',
                      'Read main.py', 'awaiting result', 'reviewer', 'running']:
            self.assertIn(value, text)
        self.assertNotIn('CLAUDE', text)
        self.assertNotIn('0 AGENTS.md', text)
        self.assertIn('\033[1m', self.render(color=True))

    def test_context_uses_latest_window_count_not_cumulative_session_tokens(self):
        data = copy.deepcopy(PAYLOAD)
        data['total_tokens'] = 9000000
        self.assertIn('37%', self.render(data))

    def test_nonstandard_quota_window_keeps_its_real_duration(self):
        data = copy.deepcopy(PAYLOAD)
        data['limits'][0]['window_minutes'] = 60
        text = self.render(data)
        self.assertIn('1H QUOTA USED', text)
        self.assertNotIn('5H', text)

    def test_no_claude_state_or_raw_payload_is_used(self):
        data = copy.deepcopy(PAYLOAD)
        data.update(command='SECRET_COMMAND', output='SECRET_OUTPUT', prompt='SECRET_PROMPT',
                    state={'used': {'skills': ['CLAUDE_PRIVATE']}})
        with (patch('context_statusline.load_state', side_effect=AssertionError('Claude state')),
             patch('context_statusline.config_snapshot', side_effect=AssertionError('Claude config')),
             patch('context_statusline.task_snapshot', side_effect=AssertionError('Claude tasks'))):
            text = self.render(data)
        self.assertNotIn('SECRET', text)
        self.assertNotIn('CLAUDE_PRIVATE', text)

    def test_sparse_invalid_and_unknown_versions_are_disclosed(self):
        self.assertIn('unavailable', self.render({'schema_version': 1, 'host': 'codex'}))
        for data in [{}, {'schema_version': 2, 'host': 'codex'}, {'schema_version': 1, 'host': 'claude'}]:
            self.assertIn('unsupported', self.render(data).lower())
        data = copy.deepcopy(PAYLOAD)
        data.update(plan=[None, {'step': 'Future task', 'status': 'future'}], tools='invalid', agents=[{}])
        self.assertIn('incomplete', self.render(data).lower())
        self.assertNotIn('Future task', self.render(data))

    def test_labels_controls_and_width_are_bounded(self):
        data = copy.deepcopy(PAYLOAD)
        data['plan'][1]['step'] = 'Build 模型 ' + 'longword' * 35 + '\x1b]52;c;SECRET\x07'
        for width in [2, 12, 44, 72, 100, 128]:
            text = self.render(data, width)
            self.assertNotIn('\x1b', text)
            self.assertTrue(all(cell_width(line) <= width for line in text.splitlines()))

    def test_child_activity_with_same_call_id_stays_on_child_row(self):
        data = copy.deepcopy(PAYLOAD)
        data['agents'][0]['tools'] = [{'id': 'call-1', 'tool': 'Edit', 'target': '/tmp/child.py', 'at': NOW-5}]
        data['agents'][0]['status'] = 'errored'
        text = self.render(data)
        child = next(line for line in text.splitlines() if 'reviewer' in line)
        main = next(line for line in text.splitlines() if 'MAIN' in line)
        self.assertIn('Read main.py', main)
        self.assertNotIn('child.py', main)
        self.assertIn('failed', child)
        # Failed agents must not retain an active pending-result indicator.
        self.assertNotIn('awaiting result', child)
        data['agents'][0]['status'] = 'running'
        self.assertIn('Edit child.py', self.render(data))

    def test_large_plan_discloses_display_budget_and_keeps_output_bounded(self):
        data = copy.deepcopy(PAYLOAD)
        data['plan'] = [{'step': 'Long task ' + 'x' * 500, 'status': 'pending'} for _ in range(256)]
        text = self.render(data, width=128, color=True)
        self.assertLessEqual(len(text.splitlines()), 64)
        self.assertLessEqual(len(text.encode()), 65536)
        self.assertIn('clipped', text)

    def test_cli_always_emits_utf8_even_when_pipe_encoding_is_ascii(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'codex_statusline.py'), '--plain'],
            input=json.dumps(PAYLOAD).encode(), capture_output=True,
            env=dict(os.environ, PYTHONIOENCODING='ascii'), timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('░', result.stdout.decode('utf-8'))

    def test_cli_consumes_versioned_snapshot_without_writing_state(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'codex_statusline.py'), '--plain'],
            input=json.dumps(PAYLOAD), text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Build', result.stdout)
        self.assertNotIn('CLAUDE.md', result.stdout)

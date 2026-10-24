"""Exercise the executable boundary; fixtures contain no private session data."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import unittest
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/session.json').read_text())
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def invoke(payload, columns=100, *args):
    env = dict(os.environ, COLUMNS=str(columns), NO_COLOR='1', TERM='xterm-256color')
    # Never allow tests to inspect or update the real activity cache.
    env['CONTEXT_STATUSLINE_STATE_DIR'] = str(ROOT / '.test-nonexistent-state')
    return subprocess.run(['bash', str(ROOT / 'context-bar.sh'), '--plain', *args],
                          input=payload if isinstance(payload, str) else json.dumps(payload),
                          text=True, capture_output=True, env=env, timeout=5)


def visible(s):
    return ANSI.sub('', s)


class MainRendererTests(unittest.TestCase):
    def test_supplied_cost_is_not_repriced_from_tokens(self):
        result = invoke(FIXTURE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('$12.34', visible(result.stdout))
        self.assertNotIn('$1.88', visible(result.stdout))

    def test_remaining_tokens_come_from_supplied_window(self):
        self.assertIn('126k left', visible(invoke(FIXTURE).stdout))

    def test_missing_metrics_are_not_healthy_zeroes(self):
        text = visible(invoke({}).stdout)
        self.assertIn('unavailable', text.lower())
        self.assertNotIn('0%', text)
        self.assertNotIn('$0.00', text)

    def test_actual_zero_values_remain_visible(self):
        payload = copy.deepcopy(FIXTURE)
        payload['context_window']['used_percentage'] = 0
        payload['cost']['total_cost_usd'] = 0
        text = visible(invoke(payload).stdout)
        self.assertIn('0%', text)
        self.assertIn('$0.00', text)

    def test_more_used_weekly_limit_takes_priority(self):
        payload = copy.deepcopy(FIXTURE)
        payload['rate_limits']['seven_day'] = {'used_percentage': 98, 'resets_at': 4102444800}
        text = visible(invoke(payload).stdout)
        self.assertIn('7D QUOTA USED', text)
        self.assertIn('98%', text)

    def test_expired_window_is_not_shown_as_current(self):
        payload = copy.deepcopy(FIXTURE)
        payload['rate_limits']['five_hour']['resets_at'] = 1
        payload['rate_limits']['seven_day'] = {'used_percentage': 68, 'resets_at': 4102444800}
        text = visible(invoke(payload).stdout)
        self.assertIn('7D QUOTA USED', text)
        self.assertNotIn('5H QUOTA USED', text)

    def test_malformed_and_nonobject_json_do_not_render_a_valid_session(self):
        for payload in ['{broken', 'null', '[]', 'true']:
            with self.subTest(payload=payload):
                result = invoke(payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('0%', visible(result.stdout))

    def test_oversized_payload_is_rejected(self):
        result = invoke(json.dumps({'model': {'display_name': 'a' * 1100000}}))
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_metrics_do_not_become_numbers(self):
        for bad in [True, -1, float('nan'), '37', {}, 101]:
            with self.subTest(bad=bad):
                payload = copy.deepcopy(FIXTURE)
                payload['context_window'] = {'used_percentage': bad}
                text = visible(invoke(payload).stdout)
                self.assertIn('unavailable', text.lower())
                self.assertNotIn('nan', text.lower())

    def test_custom_model_is_data_not_a_format_string(self):
        payload = copy.deepcopy(FIXTURE)
        payload['model']['display_name'] = 'Test 50% model'
        result = invoke(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Test 50% model', visible(result.stdout))

    def test_terminal_escape_and_bidi_text_are_not_executed(self):
        payload = copy.deepcopy(FIXTURE)
        payload['model']['display_name'] = 'Test\x1b]52;c;secret\x07\n\u202efake'
        result = invoke(payload)
        self.assertNotIn('\x1b', result.stdout)
        self.assertNotIn('\u202e', result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 4)

    def test_non_tty_execution_is_quiet(self):
        result = invoke(FIXTURE)
        self.assertEqual(result.stderr, '')

    def test_width_budget_includes_wide_unicode(self):
        payload = copy.deepcopy(FIXTURE)
        payload['model']['display_name'] = '模型' * 20
        for columns in [12, 24, 44, 72, 100, 150]:
            with self.subTest(columns=columns):
                result = invoke(payload, columns)
                for row in visible(result.stdout).splitlines():
                    cells = sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in row)
                    self.assertLessEqual(cells, columns, row)

    def test_ascii_and_plain_modes_have_no_escape_sequences(self):
        result = invoke(FIXTURE, 100, '--ascii')
        self.assertTrue(result.stdout.isascii())
        self.assertNotIn('\x1b', result.stdout)

    def test_normal_session_has_no_health_badge_or_elapsed_instrument(self):
        text = visible(invoke(FIXTURE).stdout)
        self.assertIn('EST. COST', text)
        self.assertNotIn('12m', text)
        self.assertNotIn('healthy', text.lower())
        self.assertNotIn('PRESSURE', text)

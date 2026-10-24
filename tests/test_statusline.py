"""Exercise the executable boundary; fixtures contain no private session data."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'tests/fixtures/session.json').read_text())
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def invoke(payload, columns=100, *args):
    env = dict(os.environ, COLUMNS=str(columns), NO_COLOR='1', TERM='xterm-256color')
    # Never allow tests to inspect or update the real activity cache.
    env['CONTEXT_STATUSLINE_STATE_DIR'] = str(ROOT / '.test-nonexistent-state')
    env['CLAUDE_CONFIG_DIR'] = str(ROOT / '.test-nonexistent-state/config')
    env['CLAUDE_CODE_TASK_LIST_ID'] = ''
    return subprocess.run(['bash', str(ROOT / 'context-bar.sh'), '--plain', *args],
                          input=payload if isinstance(payload, str) else json.dumps(payload),
                          text=True, capture_output=True, env=env, timeout=5)


def visible(s):
    return ANSI.sub('', s)


class MainRendererTests(unittest.TestCase):
    def test_diagnostics_normalize_invalid_cache_values_to_strict_json(self):
        # Raw pass-through would either emit non-JSON numbers or invalid cache types.
        for bad in [float('nan'), float('inf'), -1, 1.01, True, '0.5', {}, 10 ** 1000]:
            with self.subTest(bad=bad):
                result = invoke({'prompt_cache': {'warm': bad, 'hit_ratio': bad}},
                                100, '--diagnostics')
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout, parse_constant=lambda value: self.fail(
                    'Diagnostics emitted non-JSON number: ' + value))
                self.assertEqual(parsed['prompt_cache'], {
                    'warm': bad if isinstance(bad, bool) else None, 'hit_ratio': None})

    def test_diagnostics_preserve_valid_cache_values(self):
        for warm, ratio in [(True, 0.75), (False, 0), (True, 1)]:
            with self.subTest(warm=warm, ratio=ratio):
                cache = {'warm': warm, 'hit_ratio': ratio}
                result = invoke({'prompt_cache': cache}, 100, '--diagnostics')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['prompt_cache'], cache)

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

    def test_huge_numeric_metric_is_unavailable_without_a_traceback(self):
        payload = copy.deepcopy(FIXTURE)
        payload['context_window'] = {'used_percentage': 10 ** 1000}
        result = invoke(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('unavailable', visible(result.stdout))

    def test_invalid_unicode_session_identifier_does_not_break_the_display(self):
        payload = copy.deepcopy(FIXTURE)
        payload['session_id'] = '\ud800'
        result = invoke(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('$12.34', result.stdout)

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
        self.assertEqual(len(result.stdout.splitlines()), len(invoke(FIXTURE).stdout.splitlines()))

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
                    self.assertLessEqual(cells, columns - 4, row)

    def test_header_names_the_repository_that_owns_the_branch(self):
        # Session started in a home folder; work happens in a repository below it.
        with tempfile.TemporaryDirectory() as home:
            repo = Path(home) / 'tool-repo'
            (repo / 'src').mkdir(parents=True)
            subprocess.run(['git', 'init', '-q', '-b', 'topic', str(repo)], check=True)
            payload = copy.deepcopy(FIXTURE)
            payload['workspace'] = {'project_dir': home, 'current_dir': str(repo / 'src')}
            header = visible(invoke(payload, 100).stdout).splitlines()[0]
            self.assertTrue(header.startswith('tool-repo / topic'), header)

    def test_rule_fills_footer_inside_claude_inset(self):
        # COLUMNS is the full terminal; Claude's footer spacing takes four cells.
        rows = visible(invoke(FIXTURE, 100).stdout).splitlines()
        self.assertIn('─' * 96, rows)
        self.assertTrue(all(len(row) <= 96 for row in rows))

    def test_ascii_and_plain_modes_have_no_escape_sequences(self):
        result = invoke(FIXTURE, 100, '--ascii')
        self.assertTrue(result.stdout.isascii())
        self.assertNotIn('\x1b', result.stdout)

    def test_normal_session_has_native_elapsed_time_without_health_badges(self):
        text = visible(invoke(FIXTURE).stdout)
        self.assertIn('SESSION COST', text)
        self.assertEqual(text.count('estimate'), 1)
        self.assertIn('12m3s session', text)
        self.assertNotIn('healthy', text.lower())
        self.assertNotIn('PRESSURE', text)

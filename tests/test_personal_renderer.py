"""The approved layout consumes measured snapshots without inventing state."""
import copy
import json
from pathlib import Path
import re
import unittest

from context_statusline import cell_width, render_main, render_subagents

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'tests/fixtures/session.json').read_text())
NOW = 1700000000
ANSI = re.compile(r'\x1b\[[0-9;]*m')
SNAPSHOT = {'config': {'instructions': 2, 'rules': 8, 'mcps': 6, 'hooks': 4, 'partial': False},
            'tasks': {'available': True, 'partial': False, 'tasks': [
                {'id': '1', 'subject': 'Inspect the renderer', 'status': 'completed'},
                {'id': '2', 'subject': 'Research alternatives', 'status': 'completed'},
                {'id': '3', 'subject': 'Add task and activity panels', 'status': 'in_progress'},
                {'id': '4', 'subject': 'Verify main and subagent data', 'status': 'pending'},
                {'id': '5', 'subject': 'Update documentation and examples', 'status': 'pending'}]}}


class PersonalRendererTests(unittest.TestCase):
    def render(self, width=128, state=None, snapshot=None, color=False):
        return render_main(BASE, width, color, False, NOW, state or {},
                           snapshot=SNAPSHOT if snapshot is None else snapshot)

    def test_native_elapsed_time_and_configuration_are_visible(self):
        text = self.render()
        self.assertIn('12m3s session', text)
        self.assertIn('/workspace/context-statusline', text)
        self.assertIn('2 CLAUDE.md', text)
        self.assertIn('6 MCPs configured', text)
        self.assertIn('hooks on 4 events', text)

    def test_zero_configuration_counts_are_omitted(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['config'].update(rules=0, hooks=0)
        text = self.render(snapshot=snapshot)
        self.assertIn('2 CLAUDE.md · 6 MCPs configured', text)
        self.assertNotIn('0 rules', text)
        self.assertNotIn('hooks on', text)

    def test_closing_rule_separates_instruments_from_host_lines_below(self):
        # Claude always prints its own lines under the statusline, so the rule never dangles.
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['tasks']['tasks'] = []
        self.assertEqual(set(self.render(snapshot=snapshot).splitlines()[-1]), {'─'})

    def test_alert_text_uses_terminal_foreground_and_colors_only_the_marker(self):
        data = copy.deepcopy(BASE)
        data['context_window']['used_percentage'] = 91
        text = render_main(data, 128, True, False, NOW, {}, snapshot=SNAPSHOT)
        self.assertRegex(text, r'\x1b\[38;2;217;119;6m ?! ?\x1b\[0m\x1b\[1m\x1b\[39m ?CONTEXT PRESSURE')

    def test_full_checklist_wraps_without_losing_long_subjects(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        long_subject = 'Verify 模型 labels and ' + 'continuousword' * 8
        snapshot['tasks']['tasks'].append({'id': '6', 'subject': long_subject, 'status': 'pending'})
        for width in [12, 24, 44, 72, 100, 128]:
            with self.subTest(width=width):
                text = self.render(width, snapshot=snapshot)
                self.assertIn('2/6', text)
                joined = re.sub(r'\s', '', text)
                for task in snapshot['tasks']['tasks']:
                    self.assertIn(re.sub(r'\s', '', task['subject']), joined)
                self.assertTrue(all(cell_width(line) <= width for line in text.splitlines()))

    def test_authoritative_empty_native_list_hides_legacy_todos(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['tasks']['tasks'] = []
        state = {'agents': {'@main': {'todos': [{'subject': 'Old task', 'status': 'pending'}]}}}
        text = self.render(state=state, snapshot=snapshot)
        self.assertNotIn('TASKS', text)
        self.assertNotIn('Old task', text)

    def test_rejected_native_list_does_not_activate_stale_legacy_tasks(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['tasks'] = {'available': False, 'partial': True, 'tasks': []}
        state = {'agents': {'@main': {'todos': [{'subject': 'Stale fallback', 'status': 'pending'}]}}}
        text = self.render(state=state, snapshot=snapshot)
        self.assertNotIn('Stale fallback', text)
        self.assertIn('Task list incomplete', text)

    def test_only_main_legacy_todos_fill_missing_native_list(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['tasks'] = {'available': False, 'partial': False, 'tasks': []}
        state = {'agents': {'@main': {'todos': [{'subject': 'Main task', 'status': 'in_progress'}]},
                            'child': {'todos': [{'subject': 'Child task', 'status': 'pending'}]}}}
        text = self.render(state=state, snapshot=snapshot)
        self.assertIn('Main task', text)
        self.assertNotIn('Child task', text)

    def test_partial_data_is_visible_even_when_no_valid_task_remains(self):
        snapshot = copy.deepcopy(SNAPSHOT)
        snapshot['tasks'] = {'available': True, 'partial': True, 'tasks': []}
        snapshot['config']['partial'] = True
        text = self.render(snapshot=snapshot)
        self.assertIn('task list incomplete', text.lower())
        self.assertIn('config scan incomplete', text.lower())

    def test_main_and_subagent_tool_targets_stay_separate(self):
        state = {'agents': {
            '@main': {'last': NOW - 3, 'pending': {'main': {'tool': 'Read', 'target': 'main.py', 'at': NOW - 3}}},
            'child-1': {'last': NOW - 7, 'pending': {'child': {'tool': 'Edit', 'target': 'child.py', 'at': NOW - 7}}}},
            'used': {'skills': ['brainstorming'], 'mcps': ['context7']}}
        text = self.render(state=state)
        self.assertIn('MAIN', text)
        self.assertIn('Read main.py', text)
        self.assertIn('awaiting result', text)
        self.assertNotIn('child.py', text)
        self.assertIn('skills: brainstorming', text)
        self.assertIn('MCP: context7', text)
        data = {'columns': 128, 'tasks': [{'id': 'child-1', 'name': 'reviewer', 'status': 'running'}]}
        child = json.loads(render_subagents(data, 128, False, False, NOW, state))['content']
        self.assertIn('Edit child.py', child)
        self.assertNotIn('main.py', child)
        self.assertEqual(len(child.splitlines()), 1)

    def test_stale_activity_and_empty_usage_do_not_make_bands(self):
        state = {'agents': {'@main': {'last': NOW - 86401, 'pending': {'old': {'tool': 'Read', 'at': NOW - 86401}}}}}
        text = self.render(state=state)
        self.assertNotIn('MAIN', text)
        self.assertNotRegex(text, r'(?m)^USED\s')

    def test_neutral_text_preserves_meter_color_without_purple(self):
        text = self.render(color=True)
        self.assertNotIn('\x1b[38;2;165;180;252m', text)
        self.assertIn('\x1b[39m37%', text)
        self.assertIn('\x1b[38;2;22;163;74m█', text)
        self.assertIn('Add task and activity panels', ANSI.sub('', text))

    def test_meter_fills_are_mid_tones_that_hold_on_light_and_dark(self):
        # Fills need >= 3:1 non-text contrast on white and on a near-black terminal.
        def luminance(rgb):
            channel = [c / 255 for c in rgb]
            channel = [c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4 for c in channel]
            return .2126 * channel[0] + .7152 * channel[1] + .0722 * channel[2]
        text = self.render(color=True)
        fills = {tuple(map(int, m)) for m in re.findall(r'\x1b\[38;2;(\d+);(\d+);(\d+)m[▏▎▍▌▋▊▉█]', text)}
        self.assertTrue(fills)
        for rgb in fills:
            level = luminance(rgb)
            self.assertGreaterEqual(1.05 / (level + .05), 3, rgb)
            self.assertGreaterEqual((level + .05) / (luminance((30, 30, 30)) + .05), 3, rgb)

    def test_neutral_text_follows_terminal_foreground_on_any_theme(self):
        text = self.render(color=True)
        # Fixed light greys vanish on light terminal themes.
        for rgb in ['229;231;235', '244;245;247', '166;173;183', '126;135;147', '48;60;76', '57;71;92']:
            self.assertNotIn(f'\x1b[38;2;{rgb}m', text)
        self.assertIn('\x1b[2m', text)

    def test_current_task_has_bold_emphasis(self):
        self.assertRegex(self.render(color=True), r'\x1b\[1m[^\n]*Add task and activity panels')

    def test_wide_header_meter_and_value_columns_align(self):
        lines = self.render().splitlines()
        header = next(i for i, line in enumerate(lines) if '5H QUOTA USED' in line)
        x = lines[header].index('5H QUOTA USED')
        self.assertEqual(lines[header + 2].index('22%'), x)
        self.assertIn(lines[header + 1][x], '█▏▎▍▌▋▊▉░')
        self.assertLessEqual(len(lines), 12)

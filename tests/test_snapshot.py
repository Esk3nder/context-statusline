"""Bounded local snapshots use synthetic files only."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from session_snapshot import config_snapshot, task_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'home/.claude'
        self.config.mkdir(parents=True)
        self.project = self.root / 'work/project'
        self.project.mkdir(parents=True)
        self.tasks = self.config / 'tasks/session-1'
        self.tasks.mkdir(parents=True)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def snapshot(self, **kwargs):
        return task_snapshot('session-1', self.config, **kwargs)

    def test_native_tasks_refresh_updates_deletions_and_keep_exact_ids(self):
        one, two = self.tasks / '1.json', self.tasks / '20.json'
        self.write(one, {'id': '1', 'subject': 'Inspect', 'status': 'completed', 'description': 'not exposed'})
        self.write(two, {'id': '20', 'subject': 'Build', 'status': 'in_progress'})
        result = self.snapshot()
        self.assertEqual(result, {'available': True, 'partial': False, 'tasks': [
            {'id': '1', 'subject': 'Inspect', 'status': 'completed'},
            {'id': '20', 'subject': 'Build', 'status': 'in_progress'}]})
        self.write(two, {'id': '20', 'subject': 'Build renamed', 'status': 'completed'})
        one.unlink()
        self.assertEqual(self.snapshot()['tasks'], [{'id': '20', 'subject': 'Build renamed', 'status': 'completed'}])

    def test_existing_empty_list_is_authoritative(self):
        self.assertEqual(self.snapshot(), {'available': True, 'partial': False, 'tasks': []})
        self.assertFalse(task_snapshot('missing-session', self.config)['available'])

    def test_long_numeric_ids_do_not_break_other_tasks(self):
        for identifier in ['1', '9' * 24]:
            self.write(self.tasks / (identifier + '.json'), {
                'id': identifier, 'subject': 'Keep ' + identifier, 'status': 'pending'})
        self.assertEqual(len(self.snapshot()['tasks']), 2)

    def test_task_limit_is_disclosed_instead_of_silent_truncation(self):
        for i in range(257):
            self.write(self.tasks / f'{i}.json', {'id': str(i), 'subject': f'Task {i}', 'status': 'pending'})
        result = self.snapshot()
        self.assertEqual(len(result['tasks']), 256)
        self.assertTrue(result['partial'])

    def test_shared_list_is_selected_explicitly_without_session_fallback(self):
        self.write(self.config / 'tasks/shared/7.json', {'id': '7', 'subject': 'Shared', 'status': 'pending'})
        self.assertEqual(self.snapshot(list_id='shared')['tasks'][0]['id'], '7')
        self.assertFalse(self.snapshot(list_id='missing')['available'])

    def test_task_list_paths_and_symlinks_cannot_escape(self):
        self.write(self.config / 'outside/7.json', {'id': '7', 'subject': 'Do not read', 'status': 'pending'})
        for name in ['../outside', '/tmp', '..', '.', 'a/b', 'bad\x00name']:
            with self.subTest(name=name):
                self.assertFalse(self.snapshot(list_id=name)['available'])
        (self.config / 'tasks/linked').symlink_to(self.config / 'outside', target_is_directory=True)
        self.assertFalse(self.snapshot(list_id='linked')['available'])
        (self.tasks / '7.json').symlink_to(self.config / 'outside/7.json')
        self.assertEqual(self.snapshot()['tasks'], [])
        self.assertTrue(self.snapshot()['partial'])

    def test_unknown_oversized_or_malformed_task_records_are_disclosed(self):
        self.write(self.tasks / '1.json', {'id': '1', 'subject': 'Known', 'status': 'pending'})
        self.write(self.tasks / '2.json', {'id': '2', 'subject': 'Future', 'status': 'future_state'})
        (self.tasks / '3.json').write_text('{broken')
        self.write(self.tasks / '4.json', {'id': '4', 'subject': 'Oversized',
            'status': 'pending', 'description': 'x' * 70000})
        result = self.snapshot()
        self.assertTrue(result['partial'])
        self.assertEqual([task['id'] for task in result['tasks']], ['1'])

    def test_task_identity_mismatch_is_not_guessed_and_controls_are_removed(self):
        self.write(self.tasks / '9.json', {'id': '7', 'subject': 'Wrong', 'status': 'pending'})
        self.write(self.tasks / '2.json', {'id': '2', 'subject': 'Safe\x1b\u202e\nlabel', 'status': 'pending'})
        result = self.snapshot()
        self.assertEqual([task['id'] for task in result['tasks']], ['2'])
        self.assertNotIn('\x1b', result['tasks'][0]['subject'])
        self.assertNotIn('\u202e', result['tasks'][0]['subject'])
        self.assertTrue(result['partial'])

    def test_configuration_deduplicates_files_servers_and_hook_categories(self):
        (self.config / 'CLAUDE.md').write_text('not read as model context')
        (self.project / 'CLAUDE.md').write_text('project instruction')
        rules = self.project / '.claude/rules'
        rules.mkdir(parents=True)
        (rules / 'one.md').write_text('one')
        os.link(rules / 'one.md', rules / 'same.md')
        self.write(self.config / 'settings.json', {'mcpServers': {'same': {}, 'global': {}}, 'hooks': {'PreToolUse': []}})
        self.write(self.project / '.mcp.json', {'mcpServers': {'same': {}, 'project': {}}})
        self.write(self.project / '.claude/settings.local.json', {
            'disabledMcpjsonServers': ['project'], 'disabledMcpServers': ['global'],
            'hooks': {'PreToolUse': [], 'PostToolUse': []}})
        result = config_snapshot(self.project, self.config, self.root / 'home')
        self.assertEqual(result, {'instructions': 2, 'rules': 1, 'mcps': 1, 'hooks': 2, 'partial': False})

    def test_configuration_follows_project_ancestors_and_bounds_rule_cycles(self):
        (self.project / 'CLAUDE.md').write_text('parent')
        subdir = self.project / 'src/deep'
        subdir.mkdir(parents=True)
        rules = self.project / '.claude/rules'
        rules.mkdir(parents=True)
        (rules / 'one.md').write_text('one')
        (rules / 'cycle').symlink_to(rules, target_is_directory=True)
        result = config_snapshot(subdir, self.config, self.root / 'home')
        self.assertEqual(result['instructions'], 1)
        self.assertEqual(result['rules'], 1)
        self.assertTrue(result['partial'])

    def test_unreadable_config_format_is_partial_without_exposing_values(self):
        (self.config / 'settings.json').write_text('{broken secret')
        result = config_snapshot(self.project, self.config, self.root / 'home')
        self.assertTrue(result['partial'])
        self.assertNotIn('secret', json.dumps(result))

    def test_valid_large_account_configuration_uses_a_separate_limit(self):
        self.write(self.root / 'home/.claude.json', {
            'history': 'x' * 112127, 'mcpServers': {'global-server': {}}})
        result = config_snapshot(self.project, self.config, self.root / 'home')
        self.assertEqual(result['mcps'], 1)
        self.assertFalse(result['partial'])

    def test_configuration_limit_remains_bounded(self):
        self.write(self.config / 'settings.json', {'history': 'x' * (1024 * 1024 + 1),
            'mcpServers': {'too-large': {}}})
        self.assertTrue(config_snapshot(self.project, self.config, self.root / 'home')['partial'])

    def test_rejected_native_list_is_distinct_from_a_missing_list(self):
        (self.config / 'tasks/unsafe').symlink_to(self.tasks, target_is_directory=True)
        self.assertTrue(self.snapshot(list_id='unsafe')['partial'])
        self.assertFalse(self.snapshot(list_id='missing')['partial'])

    def test_unsupported_recognized_config_shapes_are_partial(self):
        for field, value in [('mcpServers', []), ('hooks', []), ('disabledMcpServers', 'x'),
                             ('disabledMcpjsonServers', [1]), ('mcpServers', {'invalid': []}),
                             ('hooks', {'PreToolUse': 'invalid'})]:
            with self.subTest(field=field, value=value):
                self.write(self.config / 'settings.json', {field: value})
                self.assertTrue(config_snapshot(self.project, self.config, self.root / 'home')['partial'])

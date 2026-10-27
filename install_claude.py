#!/usr/bin/env python3
"""Add this checkout's statusline to Claude Code's user settings, or remove it again.

Only the entries this checkout generates are added or removed; other settings and hooks are
kept. A changed file is backed up first. Use --dry-run to see the change without writing it.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from context_statusline import settings_fragment
from session_snapshot import config_root

LINES = ('statusLine', 'subagentStatusLine')


def settings_path():
    return config_root()/'settings.json'


def load(path):
    if not path.exists():
        return {}
    settings = json.loads(path.read_text())
    if not isinstance(settings, dict):
        raise ValueError(f'{path} does not hold a JSON object')
    return settings


def ours(group, command):
    return isinstance(group, dict) and group.get('hooks') == [{'type': 'command', 'command': command, 'timeout': 1}]


def install(settings, observers, replace):
    fragment = settings_fragment()
    result = json.loads(json.dumps(settings))
    for key in LINES:
        current = result.get(key)
        if current not in (None, fragment[key]) and not replace:
            raise ValueError(f'{key} already runs {json.dumps(current)}; '
                             'rerun with --replace to switch it to this statusline')
        result[key] = fragment[key]
    if observers:
        hooks = result.setdefault('hooks', {})
        if not isinstance(hooks, dict):
            raise ValueError('settings "hooks" is not an object; merge the --settings output by hand')
        for event, groups in fragment['hooks'].items():
            existing = hooks.setdefault(event, [])
            if not isinstance(existing, list):
                raise ValueError(f'settings hooks.{event} is not a list; merge the --settings output by hand')
            if not any(ours(group, groups[0]['hooks'][0]['command']) for group in existing):
                existing.append(groups[0])
    return result


def uninstall(settings):
    fragment = settings_fragment()
    result = json.loads(json.dumps(settings))
    for key in LINES:
        if result.get(key) == fragment[key]:
            del result[key]
    hooks = result.get('hooks')
    if isinstance(hooks, dict):
        for event, groups in fragment['hooks'].items():
            existing = hooks.get(event)
            if isinstance(existing, list):
                kept = [group for group in existing if not ours(group, groups[0]['hooks'][0]['command'])]
                if kept: hooks[event] = kept
                elif existing: del hooks[event]
        if not hooks and settings.get('hooks'):
            del result['hooks']
    return result


def render(settings):
    return json.dumps(settings, indent=2) + '\n'


def write(path, text):
    """Back up the current file, then replace it atomically with the same permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = None
    if path.exists():
        mode = path.stat().st_mode & 0o777
        backup = path.with_name(f'{path.name}.{time.strftime("%Y%m%d-%H%M%S")}.bak')
        backup.write_bytes(path.read_bytes())
        print(f'Backed up {path} to {backup}', file=sys.stderr)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.settings-', delete=False) as staged:
        staged.write(text)
    if mode is not None:
        os.chmod(staged.name, mode)
    os.replace(staged.name, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog='The settings file is $CLAUDE_CONFIG_DIR/settings.json, '
                                            'or ~/.claude/settings.json when that is unset.')
    parser.add_argument('--observers', action='store_true',
                        help='also add the metadata-only activity hooks (tool targets, used skills/MCPs)')
    parser.add_argument('--replace', action='store_true',
                        help='switch an existing statusLine/subagentStatusLine from another tool to this one')
    parser.add_argument('--uninstall', action='store_true', help='remove only the entries this checkout added')
    parser.add_argument('--dry-run', action='store_true', help='print the change as a diff and write nothing')
    args = parser.parse_args()
    if args.uninstall and (args.observers or args.replace):
        parser.error('--uninstall removes everything this checkout added; it takes no other options')
    path = settings_path()
    try:
        before = load(path)
        after = uninstall(before) if args.uninstall else install(before, args.observers, args.replace)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'No change made: {exc}\n')
    old, new = (render(before) if path.exists() else ''), render(after)
    if before == after:
        print(f'{path} already {"has no" if args.uninstall else "has the"} context-statusline entries', file=sys.stderr)
        return 0
    if args.dry_run:
        sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), str(path), str(path)))
        return 0
    try:
        write(path, new)
    except OSError as exc:
        parser.exit(1, f'No change made: {exc}\n')
    print(path)
    print('Updated. Claude Code picks up saved settings; open a new session if the footer does not change.',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

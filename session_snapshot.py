"""Read bounded local configuration/task metadata; never execute config or read transcripts.

Task directory: https://code.claude.com/docs/en/interactive-mode#task-list
Its per-file JSON format is version-sensitive; unknown records are disclosed.
"""
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

MAX_JSON = 65536
MAX_TASKS = 256
MAX_ENTRIES = 2000


def metadata(value, limit=512):
    if not isinstance(value, str):
        return ''
    return ''.join(' ' if unicodedata.category(c) in ('Cc', 'Cf', 'Cs') else c
                   for c in value[:limit]).strip()


def config_root():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or str(Path.home() / '.claude')).expanduser()


def read_object(path):
    """Return (object, invalid); missing optional files are not errors."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None, False
    except (OSError, ValueError):
        return None, True
    try:
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON:
                return None, True
            raw = stream.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            return None, True
        value = json.loads(raw)
        return (value, False) if isinstance(value, dict) else (None, True)
    except (OSError, ValueError, RecursionError):
        return None, True


def task_snapshot(session_id, config_dir=None, list_id=None):
    result = {'available': False, 'partial': False, 'tasks': []}
    selected = list_id if list_id is not None else os.environ.get('CLAUDE_CODE_TASK_LIST_ID') or session_id
    if not isinstance(selected, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,255}', selected):
        return result
    root = Path(config_dir) if config_dir is not None else config_root()
    directory = root / 'tasks' / selected
    try:
        if any(path.is_symlink() for path in (root, root / 'tasks', directory)):
            return result
        if not directory.is_dir():
            return result
        result['available'] = True
        paths = []
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ENTRIES:
                    result['partial'] = True
                    break
                if entry.name.endswith('.json'):
                    paths.append(Path(entry.path))
                    if len(paths) > MAX_TASKS:
                        result['partial'] = True
                        break
        for path in sorted(paths[:MAX_TASKS], key=lambda p: (not p.stem.isdigit(),
                           int(p.stem) if p.stem.isdigit() else p.stem)):
            value, invalid = read_object(path)
            if value is None:
                result['partial'] = True
                continue
            identifier, subject, status_value = value.get('id'), value.get('subject'), value.get('status')
            if (not isinstance(identifier, str) or identifier != path.stem
                    or not isinstance(subject, str) or not subject.strip()
                    or status_value not in ('pending', 'in_progress', 'completed')):
                result['partial'] = True
                continue
            if len(subject) > 512:
                result['partial'] = True
            result['tasks'].append({'id': identifier, 'subject': metadata(subject), 'status': status_value})
    except (OSError, ValueError, TypeError):
        result['partial'] = True
    return result


def config_snapshot(cwd, config_dir=None, home=None):
    home = Path(home) if home is not None else Path.home()
    root = Path(config_dir) if config_dir is not None else config_root()
    result = {'instructions': 0, 'rules': 0, 'mcps': 0, 'hooks': 0, 'partial': False}
    seen_files, seen_dirs, servers, disabled, hooks = set(), set(), set(), set(), set()
    budget = MAX_ENTRIES

    def count_file(path, kind):
        try:
            info = path.stat()
            identity = (info.st_dev, info.st_ino)
            if stat.S_ISREG(info.st_mode) and identity not in seen_files:
                seen_files.add(identity)
                result[kind] += 1
        except OSError:
            pass

    def rules(directory):
        nonlocal budget
        try:
            if directory.is_symlink():
                result['partial'] = True
                return
            if not directory.is_dir():
                return
            info = directory.stat()
            identity = (info.st_dev, info.st_ino)
            if identity in seen_dirs:
                return
            seen_dirs.add(identity)
            with os.scandir(directory) as entries:
                for entry in entries:
                    budget -= 1
                    if budget < 0:
                        result['partial'] = True
                        return
                    if entry.is_symlink():
                        result['partial'] = True
                    elif entry.is_dir(follow_symlinks=False):
                        rules(Path(entry.path))
                    elif entry.name.endswith('.md'):
                        count_file(Path(entry.path), 'rules')
        except (OSError, RecursionError):
            result['partial'] = True

    def settings(path):
        value, invalid = read_object(path)
        result['partial'] |= invalid
        if value is None:
            return
        mcp = value.get('mcpServers')
        if isinstance(mcp, dict):
            servers.update(name for name in mcp if isinstance(name, str))
        configured_hooks = value.get('hooks')
        if isinstance(configured_hooks, dict):
            hooks.update(configured_hooks)
        for field in ('disabledMcpServers', 'disabledMcpjsonServers'):
            names = value.get(field)
            if isinstance(names, list):
                disabled.update(name for name in names if isinstance(name, str))

    count_file(root / 'CLAUDE.md', 'instructions')
    count_file(root / 'CLAUDE.local.md', 'instructions')
    rules(root / 'rules')
    settings(root / 'settings.json')
    # Claude uses ~/.claude.json, or <CLAUDE_CONFIG_DIR>/.claude.json for custom dirs.
    settings(home / '.claude.json' if root == home / '.claude' else root / '.claude.json')
    try:
        directory = Path(cwd) if isinstance(cwd, (str, Path)) else None
        if directory is not None and directory.is_dir():
            ancestors = [directory, *directory.parents]
            if len(ancestors) > 32:
                result['partial'] = True
            for parent in reversed(ancestors[:32]):
                count_file(parent / 'CLAUDE.md', 'instructions')
                count_file(parent / 'CLAUDE.local.md', 'instructions')
                local = parent / '.claude'
                count_file(local / 'CLAUDE.md', 'instructions')
                count_file(local / 'CLAUDE.local.md', 'instructions')
                rules(local / 'rules')
                if local != root:
                    settings(local / 'settings.json')
                settings(local / 'settings.local.json')
                settings(parent / '.mcp.json')
    except (OSError, ValueError):
        result['partial'] = True
    result.update(mcps=len(servers - disabled), hooks=len(hooks))
    return result

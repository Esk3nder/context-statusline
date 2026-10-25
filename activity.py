"""Private, bounded observer metadata. Never reads transcripts or retains raw payloads.

Events: https://code.claude.com/docs/en/hooks#common-input-fields
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
from urllib.parse import quote

from session_snapshot import metadata

TTL = 86400
EVENTS = ('SubagentStart', 'SubagentStop', 'PreToolUse', 'PostToolUse',
          'PostToolUseFailure', 'PermissionRequest', 'PermissionDenied',
          'PostCompact', 'SessionEnd')


def key(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    try:
        return hashlib.sha256(value.encode()).hexdigest()
    except UnicodeError:
        return None


def database(create=False):
    root = Path(os.environ.get('CONTEXT_STATUSLINE_STATE_DIR',
                               str(Path.home() / '.cache/context-statusline'))).expanduser()
    if root.is_symlink():
        raise OSError('unsafe state directory')
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not root.exists():
        return None
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise OSError('unsafe state directory')
    path = root / 'activity.sqlite3'
    if create:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    if path.is_symlink():
        raise OSError('unsafe state file')
    if not path.exists():
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise OSError('unsafe state file')
    uri = 'file:' + quote(str(path.absolute()), safe='/') + ('?mode=rw' if create else '?mode=ro')
    # Half of the 1 s hook budget in settings_fragment(); 200 ms dropped writes on slow machines.
    connection = sqlite3.connect(uri, uri=True, timeout=.5)
    if create:
        connection.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, updated_at REAL NOT NULL, body TEXT NOT NULL)')
    return connection


def load_state(session_id, now=None):
    now = time.time() if now is None else now
    identifier = key(session_id)
    if identifier is None:
        return {}
    try:
        connection = database()
        if connection is None:
            return {}
        try:
            row = connection.execute('SELECT body FROM sessions WHERE id = ? AND updated_at > ?',
                                     (identifier, now - TTL)).fetchone()
            result = json.loads(row[0]) if row else {}
            return result if isinstance(result, dict) else {}
        finally:
            connection.close()
    except (OSError, sqlite3.Error, ValueError, AttributeError):
        return {}


def observe(data, now=None):
    """Fail-open observer; retain only allowlisted labels, IDs and timestamps."""
    now = time.time() if now is None else now
    event, identifier = data.get('hook_event_name'), key(data.get('session_id'))
    if event not in EVENTS or identifier is None:
        return
    connection = database(create=True)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('DELETE FROM sessions WHERE updated_at <= ?', (now - TTL,))
        if event == 'SessionEnd':
            connection.execute('DELETE FROM sessions WHERE id = ?', (identifier,))
            connection.commit()
            return
        row = connection.execute('SELECT body FROM sessions WHERE id = ?', (identifier,)).fetchone()
        try:
            state = json.loads(row[0]) if row else {}
        except ValueError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        state['version'] = 2
        agents = state.setdefault('agents', {})
        agent_id = data['agent_id'] if 'agent_id' in data else '@main'
        if key(agent_id) is None:
            return  # An invalid explicit child identity must never become main activity.
        record = agents.setdefault(agent_id, {})
        record.update(last=now, event=event)
        # Only selected labels below cross the input boundary; never retain raw payloads.
        tool = data.get('tool_name')
        tool = metadata(tool, 64) or 'tool'
        details = data.get('tool_input')
        details = details if isinstance(details, dict) else {}
        pending = record.setdefault('pending', {})
        call = key(data.get('tool_use_id'))
        if event == 'SubagentStart':
            record.clear()
            record.update(last=now, event=event, pending={})
        elif event == 'SubagentStop':
            record.update(ended=now, pending={})
        elif event == 'PreToolUse':
            record.pop('ended', None)
            if call:
                pending[call] = {'tool': tool, 'at': now}
                field = {'Read': 'file_path', 'Write': 'file_path', 'Edit': 'file_path',
                         'MultiEdit': 'file_path', 'NotebookEdit': 'notebook_path'}.get(tool)
                target = details.get(field) if field else None
                if isinstance(target, str) and len(target) <= 4096:
                    target = metadata(target.replace('\\', '/').rsplit('/', 1)[-1], 96)
                    if target:
                        pending[call]['target'] = target
            while len(pending) > 16:
                del pending[next(iter(pending))]
        elif event in ('PostToolUse', 'PostToolUseFailure', 'PermissionDenied'):
            pending.pop(call, None)
            if record.get('request', {}).get('tool') == tool:
                record.pop('request', None)
            if event != 'PostToolUse':
                record['failure'] = {'at': now, 'tool': tool, 'event': event}
            else:
                used = state.setdefault('used', {'skills': [], 'mcps': []})
                skill = metadata(details.get('skill'), 128) if tool == 'Skill' else ''
                server = metadata(tool.split('__', 2)[1], 64) if tool.startswith('mcp__') and tool.count('__') >= 2 else ''
                for category, name in [('skills', skill), ('mcps', server)]:
                    if name and name not in used[category]:
                        used[category].append(name)
                        used[category] = used[category][-32:]
                if tool == 'TodoWrite' and isinstance(details.get('todos'), list):
                    todos = details['todos']
                    record['todos'] = []
                    record['todos_partial'] = len(todos) > 256
                    for todo in todos[:256]:
                        if not isinstance(todo, dict):
                            record['todos_partial'] = True
                            continue
                        subject = metadata(todo.get('content'))
                        status_value = todo.get('status')
                        if subject and status_value in ('pending', 'in_progress', 'completed'):
                            record['todos'].append({'subject': subject, 'status': status_value})
                            record['todos_partial'] |= len(todo['content']) > 512
                        else:
                            record['todos_partial'] = True
        elif event == 'PermissionRequest':
            record['request'] = {'at': now, 'tool': tool}
        elif event == 'PostCompact':
            state['compaction'] = {'at': now, 'summary_supplied': bool(data.get('compact_summary'))}
        while len(agents) > 64:
            oldest = min(agents, key=lambda item: agents[item].get('last', 0))
            del agents[oldest]
        connection.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)',
                           (identifier, now, json.dumps(state, allow_nan=False)))
        connection.commit()
    finally:
        connection.close()

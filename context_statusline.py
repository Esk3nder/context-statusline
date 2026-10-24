#!/usr/bin/env python3
"""Local Claude Code statusline. Python 3.10+, standard library only.

Contract: https://code.claude.com/docs/en/statusline#available-data
"""
import argparse
import json
import math
import os
import re
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time
import unicodedata

from activity import EVENTS, load_state, observe
from session_snapshot import config_snapshot, task_snapshot

MAX_INPUT = 1024 * 1024
COLORS = {'muted': (166, 173, 183), 'ink': (229, 231, 235),
          'current': (244, 245, 247), 'dim': (126, 135, 147), 'rule': (48, 60, 76),
          'empty': (57, 71, 92), 'good': (74, 222, 128),
          'warn': (251, 191, 36), 'bad': (251, 113, 133)}


def obj(value):
    return value if isinstance(value, dict) else {}


def number(value, minimum=0, maximum=float('inf')):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) and minimum <= value <= maximum else None
    except OverflowError:
        return None


def clean(value):
    if not isinstance(value, (str, int, float)):
        return ''
    return ''.join(' ' if unicodedata.category(c) in ('Cc', 'Cf', 'Cs') else c
                   for c in str(value)[:512])


def cell_width(text):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def clip(text, width):
    result = ''
    for char in text:
        if cell_width(result + char) > width:
            break
        result += char
    return result


def segment(text, style='ink'):
    return clean(text), style


def paint(parts, width, use_color, ascii_mode):
    result, used = [], 0
    for text, style in parts:
        if ascii_mode:
            text = text.encode('ascii', 'replace').decode('ascii')
        text = clip(text, max(0, width - used))
        used += cell_width(text)
        rgb = COLORS.get(style, style)
        emphasis = '\033[1m' if style == 'current' else ''
        result.append(f'{emphasis}\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\033[0m'
                      if text and use_color else text)
    return ''.join(result)


def severity(pct):
    return 'bad' if pct is not None and pct >= 85 else 'warn' if pct is not None and pct >= 65 else 'good'


def meter(pct, count, gradient=False, ascii_mode=False):
    stops = [(74, 222, 128), (250, 204, 21), (251, 146, 60), (239, 68, 68)]
    parts = []
    for index in range(count):
        fraction = max(0, min(1, (pct or 0) * count / 100 - index))
        glyph = ('#' if fraction >= .5 else '.') if ascii_mode else (
            ' ▏▎▍▌▋▊▉█'[round(fraction * 8)] if fraction else '░')
        style = severity(pct) if fraction else 'empty'
        if gradient and fraction:
            position = index / max(1, count - 1) * 3
            start = min(2, int(position))
            mix = position - start
            style = tuple(round(a + (b - a) * mix) for a, b in zip(stops[start], stops[start + 1]))
        parts.append(segment(glyph, style))
    return parts


def compact_tokens(count):
    for scale, suffix in [(1000000, 'M'), (1000, 'k')]:
        if count >= scale:
            return f'{count / scale:.1f}'.rstrip('0').rstrip('.') + suffix
    return str(round(count))


def elapsed(seconds):
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return f'{seconds // 86400}d{seconds % 86400 // 3600}h'
    if seconds >= 3600:
        return f'{seconds // 3600}h{seconds % 3600 // 60}m'
    return f'{seconds // 60}m{seconds % 60}s' if seconds >= 60 else f'{seconds}s'


def metrics(data, now):
    context = obj(data.get('context_window'))
    pct = number(context.get('used_percentage'), maximum=100)
    if pct is None and 'used_percentage' not in context:
        remaining = number(context.get('remaining_percentage'), maximum=100)
        pct = None if remaining is None else 100 - remaining
    size = number(context.get('context_window_size'), minimum=1)
    left = None if pct is None or size is None else size * (100 - pct) / 100
    windows = []
    for key, label in [('five_hour', '5H'), ('seven_day', '7D')]:
        window = obj(obj(data.get('rate_limits')).get(key))
        usage = number(window.get('used_percentage'), maximum=100)
        reset = number(window.get('resets_at'))
        if usage is not None and (reset is None or reset > now):
            windows.append((usage, label, reset))
    quota = max(windows, key=lambda entry: entry[0]) if windows else (None, 'QUOTA', None)
    return pct, left, number(obj(data.get('cost')).get('total_cost_usd')), quota


def wrap_parts(parts, width, indent=0):
    """Wrap styled words by terminal cells; split long words without losing text."""
    width = max(1, width)
    indent = min(indent, width // 3)
    rows, line, used, space = [], [], 0, 0

    def append(text, style):
        if line and line[-1][1] == style:
            line[-1] = (line[-1][0] + text, style)
        else:
            line.append((text, style))

    def flush():
        nonlocal line, used
        rows.append(line)
        line = [segment(' ' * indent)] if indent else []
        used = indent

    for text, style in parts:
        for token in re.findall(r'\s+|\S+', text):
            if token.isspace():
                space += len(token)
                continue
            if used and used + space + cell_width(token) > width:
                flush()
                space = 0
            if space:
                gap = min(space, max(0, width - used))
                append(' ' * gap, style)
                used += gap
                space = 0
            for char in token:
                size = cell_width(char)
                if size > width:
                    char, size = '?', 1  # A two-cell glyph cannot fit a one-cell host.
                if used + size > width:
                    flush()
                append(char, style)
                used += size
    if line and any(text.strip() for text, _ in line):
        rows.append(line)
    return rows or [[]]


def identity(data, width):
    workspace = obj(data.get('workspace'))
    project = clean(obj(workspace.get('repo')).get('name') or Path(clean(
        workspace.get('project_dir') or workspace.get('current_dir') or data.get('cwd') or 'workspace')).name)
    model = clean(obj(data.get('model')).get('display_name') or 'model unavailable')
    effort = clean(obj(data.get('effort')).get('level'))
    extra = (f' · {effort}' if effort else '')
    if data.get('fast_mode') is True:
        extra += ' · fast'
    duration = number(obj(data.get('cost')).get('total_duration_ms'))
    if duration is not None:
        extra += ' · ' + elapsed(duration / 1000) + ' session'
    right = [segment(model), segment(extra, 'muted')]
    branch = clean(obj(data.get('worktree')).get('branch'))
    cwd = workspace.get('current_dir') or data.get('cwd')
    if not branch and isinstance(cwd, str) and Path(cwd).is_dir():
        try:
            branch = clean(subprocess.run(['git', '-C', cwd, 'symbolic-ref', '--short', 'HEAD'],
                           capture_output=True, text=True, timeout=.05, check=False).stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    left = project + (f' / {branch}' if branch else '')
    if width >= 76:
        available = max(8, width - cell_width(model + extra) - 2)
        left = clip(left, available)
        gap = max(2, width - cell_width(left) - cell_width(model + extra))
        return [[segment(left), segment(' ' * gap)] + right]
    return wrap_parts([segment(left)], width) + wrap_parts(right, width)


def columns(cells, width):
    result = []
    for index, cell in enumerate(cells):
        length = 0
        for text, style in cell:
            text = clip(text, max(0, width - length))
            result.append((text, style))
            length += cell_width(text)
        if index < len(cells) - 1:
            result.append(segment(' ' * max(0, width - length)))
    return result


def pending_detail(record, now):
    last = number(record.get('last'))
    if last is None or not 0 <= now - last < 86400:
        return []
    pending = []
    for value in obj(record.get('pending')).values():
        value = obj(value)
        at = number(value.get('at'))
        if at is not None and 0 <= now - at < 86400:
            pending.append((at, value))
    if not pending:
        return []
    at, latest = max(pending, key=lambda item: item[0])
    text = clean(latest.get('tool') or 'tool')
    target = clean(latest.get('target'))
    if target:
        text += ' ' + target
    detail = ' · awaiting result · ' + elapsed(now - at)
    if len(pending) > 1:
        detail += f' · +{len(pending) - 1} calls'
    return [segment(text), segment(detail, 'muted')]


def checklist(state, snapshot):
    native = obj(snapshot.get('tasks'))
    main = obj(obj(state.get('agents')).get('@main'))
    if native.get('available') or native.get('partial'):
        tasks, partial = native.get('tasks'), bool(native.get('partial'))
    else:
        tasks, partial = main.get('todos'), bool(main.get('todos_partial')) or bool(native.get('partial'))
    items = []
    if isinstance(tasks, list):
        for task in tasks[:256]:
            task = obj(task)
            subject, status = clean(task.get('subject')), task.get('status')
            if subject and status in ('pending', 'in_progress', 'completed'):
                items.append({'subject': subject, 'status': status})
            else:
                partial = True
        partial |= len(tasks) > 256
    return items, partial


def task_rows(state, snapshot, width):
    items, partial = checklist(state, snapshot)
    if not items and not partial:
        return []
    done = [task for task in items if task['status'] == 'completed']
    work = [task for task in items if task['status'] != 'completed']
    prefix = [segment('TASKS   ', 'muted'), segment(f'{len(done)}/{len(items)}  ', 'muted')]

    def subjects(tasks):
        parts = []
        for task in tasks:
            if parts:
                parts.append(segment(' · ', 'dim'))
            status = task['status']
            glyph = {'completed': '✓ ', 'in_progress': '▸ ', 'pending': '□ '}[status]
            parts.append(segment(glyph + task['subject'], 'dim' if status == 'completed' else
                                 'current' if status == 'in_progress' else 'muted'))
        return parts

    rows = wrap_parts(prefix + subjects(done or work), width, 13)
    if done and work:
        rows += wrap_parts([segment(' ' * min(13, width // 3))] + subjects(work), width, 13)
    if partial:
        rows += wrap_parts([segment(' ! Task list incomplete · unsupported, unreadable or bounded data', 'warn')], width)
    return rows


def render_main(data, width=80, color=True, ascii_mode=False, now=None, state=None, snapshot=None):
    now = time.time() if now is None else now
    state, snapshot = state or {}, snapshot or {}
    pct, left, cost, (usage, label, reset) = metrics(data, now)
    pct_text = f'{pct:g}%' if pct is not None else 'unavailable'
    room = compact_tokens(left) + ' left' if left is not None else 'room unavailable'
    quota_text = f'{usage:g}%' if usage is not None else 'unavailable'
    reset_text = 'reset ' + elapsed(reset - now) if reset is not None else 'reset unavailable'
    price = 'unavailable' if cost is None else f'${cost:.4f}' if 0 < cost < .01 else f'${cost:.2f}'
    rows = identity(data, width)
    workspace = obj(data.get('workspace'))
    directory = clean(workspace.get('current_dir') or data.get('cwd'))
    config = obj(snapshot.get('config'))
    meta = [segment(directory, 'muted')] if directory else []
    if config:
        summary = (f"{config.get('instructions', 0)} CLAUDE.md · {config.get('rules', 0)} rules · "
                   f"{config.get('mcps', 0)} MCPs configured · {config.get('hooks', 0)} hook events")
        meta += [segment(('    ' if meta else '') + summary, 'dim')]
    if meta:
        rows += wrap_parts(meta, width, 2)
    rows.append([segment(('-' if ascii_mode else '─') * width, 'rule')])
    quota_label = f'{label} QUOTA USED' if usage is not None else 'QUOTA'
    instruments = [('CONTEXT USED', pct, pct_text, room, True),
                   (quota_label, usage, quota_text, reset_text, False),
                   ('EST. COST', None, price, 'session estimate', False)]
    count = 3 if width >= 100 else 2 if width >= 60 else 1
    col = width // count
    for index in range(0, 3, count):
        group = instruments[index:index + count]
        for level in range(3):
            cells = []
            for title, percent, value, detail, gradient in group:
                parts = ([segment(title, 'muted')] if level == 0 else
                         [segment(value)] if title == 'EST. COST' and level == 1 else
                         meter(percent, max(1, col - 5), gradient, ascii_mode) if level == 1 else
                         [segment(detail, 'muted')] if title == 'EST. COST' else
                         [segment(value), segment(' · ' + detail, 'muted')])
                cells.append(wrap_parts(parts, col))
            for line_index in range(max(map(len, cells))):
                rows.append(columns([cell[line_index] if line_index < len(cell) else [] for cell in cells], col))
    rows.append([segment(('-' if ascii_mode else '─') * width, 'rule')])
    main = pending_detail(obj(obj(state.get('agents')).get('@main')), now)
    if main:
        rows += wrap_parts([segment('MAIN    ', 'dim')] + main, width, 8)
    rows += task_rows(state, snapshot, width)
    used = obj(state.get('used'))
    skills = [clean(x) for x in used.get('skills', []) if isinstance(x, str)] if isinstance(used.get('skills'), list) else []
    mcps = [clean(x) for x in used.get('mcps', []) if isinstance(x, str)] if isinstance(used.get('mcps'), list) else []
    categories = (['skills: ' + ', '.join(skills)] if skills else []) + (['MCP: ' + ', '.join(mcps)] if mcps else [])
    if categories:
        rows += wrap_parts([segment('USED    ', 'dim'), segment(' · '.join(categories), 'muted')], width, 8)
    if config.get('partial'):
        rows += wrap_parts([segment(' ! Config scan incomplete', 'warn')], width)
    if pct is not None and pct >= 85:
        rows += wrap_parts([segment(f' ! CONTEXT PRESSURE · {pct_text} · {room}', 'warn')], width)
    if usage is not None and usage >= 90:
        rows += wrap_parts([segment(f' ! QUOTA PRESSURE · {label} {quota_text} · {reset_text}', 'warn')], width)
    for notice in notices(state, now):
        rows += wrap_parts(notice, width)
    return '\n'.join(paint(row, width, color, ascii_mode) for row in rows) + '\n'


def recent(value, now, seconds=60):
    stamp = number(value)
    return stamp is not None and 0 <= now - stamp <= seconds


def notices(state, now):
    rows = []
    for record in obj(state.get('agents')).values():
        record = obj(record)
        request = obj(record.get('request'))
        failure = obj(record.get('failure'))
        if recent(request.get('at'), now):
            rows.append([segment(' ! Approval requested · ' + clean(request.get('tool')) +
                                 ' · ' + elapsed(now - request['at']) + ' ago', 'warn')])
        if recent(failure.get('at'), now):
            kind = 'Permission denied' if failure.get('event') == 'PermissionDenied' else 'Tool failure reported'
            rows.append([segment(' ! ' + kind + ' · ' + clean(failure.get('tool')), 'bad')])
        if len(rows) >= 3:
            break
    compaction = obj(state.get('compaction'))
    if recent(compaction.get('at'), now):
        rows.append([segment(' Compacted ' + elapsed(now - compaction['at']) + ' ago', 'muted')])
    return rows[:3]


def render_subagents(data, width=80, color=True, ascii_mode=False, now=None, state=None):
    """Native batched input -> one JSON line per overridden task row.

    https://code.claude.com/docs/en/statusline#subagent-status-lines
    """
    now = time.time() if now is None else now
    state = state or {}
    tasks = data.get('tasks')
    result = []
    if not isinstance(tasks, list):
        return ''
    for task in tasks[:64]:
        task = obj(task)
        identifier = task.get('id')
        if not isinstance(identifier, str) or not identifier or len(identifier) > 256:
            continue
        record = obj(obj(state.get('agents')).get(identifier))  # Exact ID only, never a name guess.
        role = clean(task.get('agentType') or task.get('name') or 'agent')
        status = clean(task.get('status') or 'unknown')
        start = number(task.get('startTime'))
        end = now if status == 'running' else number(record.get('ended'))
        duration = ''
        if start is not None and end is not None and start / 1000 <= end <= now:
            duration = ' · ' + elapsed(end - start / 1000)
        style = 'bad' if status in ('failed', 'killed') else 'ink' if status == 'running' else 'dim'
        parts = [segment(role + ' '), segment(status, style), segment(duration, 'muted')]
        last = number(record.get('last'))
        if status == 'running' and last is not None and 0 <= now - last < 86400:
            request = obj(record.get('request'))
            pending = pending_detail(record, now)
            if recent(request.get('at'), now):
                parts.append(segment(' · approval requested', 'warn'))
            elif pending:
                parts += [segment(' · ', 'dim')] + pending
            else:
                parts.append(segment(' · last event ' + elapsed(now - last) + ' ago', 'muted'))
        lines = wrap_parts(parts, width, 2)
        content = '\n'.join(paint(line, width, color, ascii_mode) for line in lines)
        result.append(json.dumps({'id': identifier, 'content': content}, ensure_ascii=True))
    return '\n'.join(result) + ('\n' if result else '')


def diagnostics(data, state, now, snapshot=None):
    pct, left, cost, quota = metrics(data, now)
    cache = obj(data.get('prompt_cache'))
    return {'context_used_percentage': pct, 'context_tokens_left': left,
            'quota': {'used_percentage': quota[0], 'window': quota[1], 'resets_at': quota[2]},
            'estimated_session_cost_usd': cost, 'delegated_cost_inclusion': None,
            'context_runway': None, 'quota_exhaustion': None,
            'forecast_reason': 'No validated growth/rate history or compaction threshold',
            'compaction': state.get('compaction'), 'activity': state.get('agents', {}),
            'used': state.get('used', {}), 'local_snapshot': snapshot or {},
            'prompt_cache': {'warm': cache.get('warm') if isinstance(cache.get('warm'), bool) else None,
                             'hit_ratio': number(cache.get('hit_ratio'), maximum=1)}}


def settings_fragment():
    command = shlex.quote(str(Path(__file__).resolve().with_name('context-bar.sh')))
    return {'statusLine': {'type': 'command', 'command': command, 'refreshInterval': 5},
            'subagentStatusLine': {'type': 'command', 'command': command + ' --subagents'},
            'hooks': {event: [{'hooks': [{'type': 'command', 'command': command + ' --hook', 'timeout': 1}]}]
                      for event in EVENTS}}


def read_payload():
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError('payload exceeds 1 MiB')
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('expected a JSON object')
    return payload


def terminal_width(value):
    try:
        if isinstance(value, bool):
            return 80
        width = int(value)
        return width if 1 <= width <= 500 else 80
    except (ValueError, TypeError, OverflowError):
        return 80


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plain', action='store_true', help='disable ANSI colors')
    parser.add_argument('--ascii', action='store_true', help='use ASCII characters')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--subagents', action='store_true', help='format native subagent JSONL rows')
    modes.add_argument('--hook', action='store_true', help='record observer-only event metadata')
    modes.add_argument('--diagnostics', action='store_true', help='print measured evidence as JSON')
    modes.add_argument('--settings', action='store_true', help='print an additive settings fragment; does not edit configuration')
    args = parser.parse_args()
    if args.settings:
        print(json.dumps(settings_fragment(), indent=2))
        return 0
    try:
        data = read_payload()
    except (ValueError, UnicodeError, RecursionError):
        if not args.hook:
            print('context-statusline: input unavailable', file=sys.stderr)
        return 0 if args.hook else 1
    if args.hook:
        try:
            observe(data)
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
            pass  # Observers must not affect the agent or permission decisions.
        return 0
    color = not args.plain and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    now = time.time()
    state = load_state(data.get('session_id'), now)
    snapshot = {}
    if not args.subagents:
        cwd = obj(data.get('workspace')).get('current_dir') or data.get('cwd')
        snapshot = {'config': config_snapshot(cwd), 'tasks': task_snapshot(data.get('session_id'))}
    if args.diagnostics:
        print(json.dumps(diagnostics(data, state, now, snapshot), indent=2, allow_nan=False))
    else:
        width = terminal_width(data.get('columns') if args.subagents else os.environ.get('COLUMNS'))
        output = (render_subagents(data, width, color, args.ascii, now, state) if args.subagents else
                  render_main(data, width, color, args.ascii, now, state, snapshot))
        sys.stdout.write(output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

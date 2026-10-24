#!/usr/bin/env python3
"""Shared personal statusline for our patched Codex TUI; no transcript/cache access."""
import argparse
import json
import os
from pathlib import PurePosixPath
import sys
import time

from context_statusline import (MAX_INPUT, clean, number, obj, render_main, render_subagents,
                                segment, paint, wrap_parts, alert)


def bounded_list(value, limit=256):
    return value[:limit] if isinstance(value, list) else []


def observed_tools(raw, now):
    record = {'last': now, 'pending': {}}
    for value in bounded_list(raw, 64):
        tool = obj(value)
        identifier, name = clean(tool.get('id')), clean(tool.get('tool'))
        at = number(tool.get('at'))
        if identifier and name and at is not None:
            target = clean(tool.get('target')).replace('\\', '/')
            record['pending'][identifier] = {'tool': name, 'at': at,
                'target': PurePosixPath(target).name if target else ''}
    return record


def render_codex(payload, width=80, color=True, now=None):
    now = time.time() if now is None else now
    width = max(1, min(1000, width))
    if not isinstance(payload, dict) or payload.get('host') != 'codex' or payload.get('schema_version') != 1:
        return paint([segment('Codex statusline: unsupported snapshot', 'warn')], width, color, False) + '\n'
    context = obj(payload.get('context'))
    used, size = number(context.get('used_tokens')), number(context.get('window_tokens'), minimum=1)
    pct = min(100, 100 * used / size) if used is not None and size is not None else None
    data = {'host': 'codex', 'session_id': clean(payload.get('session_id')),
            'model': {'display_name': clean(payload.get('model'))},
            'effort': {'level': clean(payload.get('effort'))},
            'workspace': {'current_dir': clean(payload.get('cwd'))},
            'context_window': {'used_percentage': pct, 'context_window_size': size},
            'worktree': {'branch': clean(payload.get('branch'))},
            'cost': {'total_cost_usd': number(payload.get('estimated_thread_cost_usd')),
                     'total_duration_ms': number(payload.get('attached_ms'))},
            'duration_label': 'attached', 'cost_label': 'thread estimate', 'rate_limits': {'windows': []}}
    partial = False
    for raw in bounded_list(payload.get('limits'), 16):
        limit = obj(raw)
        minutes = number(limit.get('window_minutes'), minimum=1)
        usage = number(limit.get('used_percent'), maximum=100)
        if minutes is None or usage is None:
            partial = True
            continue
        label = (f'{minutes / 1440:g}D' if minutes % 1440 == 0 else
                 f'{minutes / 60:g}H' if minutes % 60 == 0 else f'{minutes:g}M')
        data['rate_limits']['windows'].append({'label': label, 'used_percentage': usage,
                                               'resets_at': number(limit.get('resets_at'))})
    tasks = []
    plan = payload.get('plan', [])
    partial |= not isinstance(plan, list) or len(plan) > 256
    for index, raw in enumerate(bounded_list(plan)):
        item = obj(raw)
        status = {'pending': 'pending', 'inProgress': 'in_progress', 'completed': 'completed'}.get(item.get('status')) if isinstance(item.get('status'), str) else None
        subject = clean(item.get('step'))
        if not status or not subject:
            partial = True
            continue
        tasks.append({'id': str(index), 'subject': subject, 'status': status})
    snapshot = {'tasks': {'available': True, 'partial': partial, 'tasks': tasks}}
    config = obj(payload.get('configuration'))
    snapshot['config'] = {key: number(config.get(key)) for key in ['instructions', 'mcps', 'hooks', 'skills']
                          if number(config.get(key)) is not None}
    state = {'agents': {'@main': observed_tools(payload.get('tools'), now)}}
    used_caps = obj(payload.get('used'))
    state['used'] = {key: [clean(value) for value in bounded_list(used_caps.get(key), 32) if isinstance(value, str)]
                     for key in ['skills', 'mcps']}
    text = render_main(data, width, color, now=now, state=state, snapshot=snapshot)
    agents = []
    for raw in bounded_list(payload.get('agents'), 64):
        item = obj(raw)
        if not clean(item.get('id')):
            continue
        identifier = clean(item.get('id'))
        status = clean(item.get('status'))
        status = {'errored': 'failed', 'interrupted': 'killed', 'pendingInit': 'pending'}.get(status, status)
        state['agents'][identifier] = observed_tools(item.get('tools'), now)
        agents.append({'id': identifier, 'agentType': clean(item.get('role')) or 'agent',
                       'status': status or 'unknown'})
    for row in render_subagents({'tasks': agents}, width, color, now=now, state=state).splitlines():
        text += json.loads(row)['content'] + '\n'
    if payload.get('partial') is True:
        text += '\n'.join(paint(row, width, color, False) for row in wrap_parts(
            alert('Codex metadata incomplete'), width)) + '\n'
    rows, size = [], 0
    for line in text.splitlines():
        encoded = len(line.encode('utf-8')) + 1
        if len(rows) >= 63 or size + encoded > 48 * 1024:
            rows.append(paint(alert('Statusline clipped · bounded display'), width, color, False))
            break
        rows.append(line)
        size += encoded
    return '\n'.join(rows) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plain', action='store_true')
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('snapshot limit')
        payload = json.loads(raw)
        columns = number(obj(payload).get('columns'), minimum=1, maximum=1000) or 80
        print(render_codex(payload, int(columns), not args.plain and 'NO_COLOR' not in os.environ), end='')
        return 0
    except (ValueError, UnicodeError, RecursionError, TypeError):
        print('Codex statusline: snapshot unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

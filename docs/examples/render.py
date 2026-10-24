"""Regenerate the README image from real renderer functions and synthetic inputs."""
import json
from pathlib import Path
import re
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from context_statusline import render_main, render_subagents  # noqa: E402

NOW = 1700000000
HERE = Path(__file__).parent
ANSI = re.compile(r'\x1b\[(?:38;2;(\d+);(\d+);(\d+)|0|1|2|39)m')
INK, FAINT = '#e5e7eb', 'rgb(122,126,132)'  # terminal foreground and its faint form on this dark card


def example(situation='quiet', width=128, color=True):
    session = json.loads((ROOT / 'tests/fixtures/session.json').read_text())
    session['cost']['total_cost_usd'] = .50
    session['worktree'] = {'branch': 'instrument-panel'}
    session['cost']['total_duration_ms'] = 1122000
    session['workspace']['current_dir'] = '~/dev/context-statusline'
    snapshot = json.loads((ROOT / 'tests/fixtures/personal.json').read_text())
    session['rate_limits']['five_hour']['resets_at'] = NOW + 7800
    tasks = json.loads((ROOT / 'tests/fixtures/subagents.json').read_text())
    tasks['tasks'][0]['startTime'] = (NOW - 192) * 1000
    tasks['tasks'][1]['startTime'] = (NOW - 200) * 1000
    state = {'agents': {'@main': {'last': NOW - 3, 'pending': {'main-call': {'tool': 'Read', 'target': 'context_statusline.py', 'at': NOW - 3}}},
                        'agent-review': {'last': NOW - 7, 'pending': {'sample-call': {'tool': 'Read', 'target': 'test_statusline.py', 'at': NOW - 7}}},
                        'agent-research': {'last': NOW - 100, 'ended': NOW - 100}},
             'used': {'skills': ['brainstorming', 'test-driven-development'], 'mcps': ['context7']}}
    if situation == 'normal':
        state = {}
        tasks['tasks'] = []
        snapshot['tasks']['tasks'] = []
    elif situation == 'approval':
        state['agents']['agent-review']['request'] = {'at': NOW - 5, 'tool': 'Bash'}
    elif situation == 'pressure':
        session['context_window']['used_percentage'] = 91
    main = render_main(session, width, color, False, NOW, state, snapshot)
    rows = [json.loads(row)['content'] for row in render_subagents(tasks, max(1, width - 8), color, False, NOW, state).splitlines()]
    # Claude owns placement/tree markers; these labels distinguish its two surfaces.
    return main + ('AGENTS  ' + '\n        '.join(rows) if rows else '')


def svg(text, width):
    rows = text.splitlines()
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * 8 + 48}" height="{len(rows) * 24 + 48}" viewBox="0 0 {width * 8 + 48} {len(rows) * 24 + 48}">',
                '<rect width="100%" height="100%" rx="8" fill="#10151e"/>',
                '<g font-family="Menlo,Consolas,monospace" font-size="13" xml:space="preserve">']
    for index, line in enumerate(rows):
        fragments, last, fill, bold = [], 0, INK, False
        for match in ANSI.finditer(line):
            if match.start() > last:
                fragments.append(f'<tspan fill="{fill}" font-weight="{600 if bold else 400}">{escape(line[last:match.start()])}</tspan>')
            if match.group() == '\x1b[1m':
                bold = True
            elif match.group() in ('\x1b[0m', '\x1b[39m'):
                fill, bold = INK, bold and match.group() == '\x1b[39m'
            elif match.group() == '\x1b[2m':
                fill = FAINT
            else:
                fill = f'rgb({match[1]},{match[2]},{match[3]})'
            last = match.end()
        fragments.append(f'<tspan fill="{fill}">{escape(line[last:])}</tspan>')
        elements.append(f'<text x="24" y="{36 + index * 24}" style="white-space:pre">{"".join(fragments)}</text>')
    return '\n'.join(elements + ['</g></svg>']) + '\n'


if __name__ == '__main__':
    HERE.mkdir(exist_ok=True)
    (HERE / 'preview.txt').write_text(example(color=False) + '\n')
    for situation in ['quiet', 'normal', 'approval', 'pressure']:
        for width in [44, 72, 100, 128]:
            name = 'preview.svg' if situation == 'quiet' and width == 128 else f'{situation}-{width}.svg'
            (HERE / name).write_text(svg(example(situation, width), width))

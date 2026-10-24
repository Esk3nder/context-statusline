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
ANSI = re.compile(r'\x1b\[(?:38;2;(\d+);(\d+);(\d+)|0)m')


def example(situation='quiet', width=100, color=True):
    session = json.loads((ROOT / 'tests/fixtures/session.json').read_text())
    session['cost']['total_cost_usd'] = .50
    session['worktree'] = {'branch': 'fix/cost'}
    session['rate_limits']['five_hour']['resets_at'] = NOW + 7800
    tasks = json.loads((ROOT / 'tests/fixtures/subagents.json').read_text())
    tasks['tasks'][0]['startTime'] = (NOW - 492) * 1000
    tasks['tasks'][1]['startTime'] = (NOW - 200) * 1000
    state = {'agents': {'agent-review': {'last': NOW - 240, 'pending': {'sample-call': {'tool': 'Bash'}}},
                        'agent-research': {'last': NOW - 100, 'ended': NOW - 100}}}
    if situation == 'normal':
        state = {}
        tasks['tasks'] = []
    elif situation == 'approval':
        state['agents']['agent-review']['request'] = {'at': NOW - 5, 'tool': 'Bash'}
    elif situation == 'pressure':
        session['context_window']['used_percentage'] = 91
    main = render_main(session, width, color, False, NOW, state)
    rows = [json.loads(row)['content'] for row in render_subagents(tasks, width - 2, color, False, NOW, state).splitlines()]
    # Claude owns placement/tree markers; these labels distinguish its two surfaces.
    return 'MAIN STATUSLINE\n' + main + ('\nNATIVE AGENT PANEL\n' + '\n'.join(rows) if rows else '')


def svg(text, width):
    rows = text.splitlines()
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width * 8 + 48}" height="{len(rows) * 24 + 48}" viewBox="0 0 {width * 8 + 48} {len(rows) * 24 + 48}">',
                '<rect width="100%" height="100%" rx="8" fill="#10151e"/>',
                '<g font-family="Menlo,Consolas,monospace" font-size="13" xml:space="preserve">']
    for index, line in enumerate(rows):
        fragments, last, fill = [], 0, '#cbd5e1'
        for match in ANSI.finditer(line):
            if match.start() > last:
                fragments.append(f'<tspan fill="{fill}">{escape(line[last:match.start()])}</tspan>')
            fill = f'rgb({match[1]},{match[2]},{match[3]})' if match[1] else '#cbd5e1'
            last = match.end()
        fragments.append(f'<tspan fill="{fill}">{escape(line[last:])}</tspan>')
        elements.append(f'<text x="24" y="{36 + index * 24}">{"".join(fragments)}</text>')
    return '\n'.join(elements + ['</g></svg>']) + '\n'


if __name__ == '__main__':
    HERE.mkdir(exist_ok=True)
    (HERE / 'preview.txt').write_text(example(color=False) + '\n')
    for situation in ['quiet', 'normal', 'approval', 'pressure']:
        for width in [44, 72, 100]:
            name = 'preview.svg' if situation == 'quiet' and width == 100 else f'{situation}-{width}.svg'
            (HERE / name).write_text(svg(example(situation, width), width))

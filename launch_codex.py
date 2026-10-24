"""Launch only the patched bundled Codex; preserve normal config/auth and CLI arguments."""
import json
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root/'manifest.json').read_text())
    binary = root/manifest.get('entrypoint', 'codex.exe' if os.name == 'nt' else 'codex')
    env = dict(os.environ)
    env['CODEX_STATUSLINE_COMMAND'] = json.dumps([sys.executable, str(root/'codex_statusline.py')])
    if sys.argv[1:] == ['update']:
        raise SystemExit('Update this patched build with install_codex.py and a new verified bundle; stock Codex updates do not contain the panel.')
    os.execve(str(binary), [str(binary), '-c', 'check_for_update_on_startup=false', *sys.argv[1:]], env)


if __name__ == '__main__':
    main()

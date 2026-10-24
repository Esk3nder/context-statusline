"""Launch only the patched bundled Codex; preserve normal config/auth and CLI arguments."""
import json
import os
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent
    binary = root/('codex.exe' if os.name == 'nt' else 'codex')
    env = dict(os.environ)
    env['CODEX_STATUSLINE_COMMAND'] = json.dumps([sys.executable, str(root/'codex_statusline.py')])
    os.execve(str(binary), [str(binary), *sys.argv[1:]], env)


if __name__ == '__main__':
    main()

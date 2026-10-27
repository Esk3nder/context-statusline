"""Launch the custom TUI; keep macOS MCP credentials in official signed Codex."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

BACKEND_SOCKET = 'CODEX_STATUSLINE_BACKEND_SOCKET'
# OpenAI's Apple Developer team is the trust anchor; it cannot be read from the program it vets.
OFFICIAL_REQUIREMENT = 'identifier "codex" and anchor apple generic and certificate leaf[subject.OU] = "2DC432GLL2"'
# Subcommands that open the interactive session and so get the panel. Every other subcommand,
# including ones a later Codex adds, goes to official Codex: the safe default for credentials.
SESSIONS = {'resume', 'fork'}


class Cli:
    """The pinned Codex CLI surface, asked of the bundled binary instead of copied by hand."""

    def __init__(self, binary):
        self.binary = str(binary)
        help_text = subprocess.run([self.binary, '--help'], check=True, capture_output=True,
                                   text=True, timeout=10).stdout
        self.value_options = {name for line in help_text.splitlines()
                              for name in re.findall(r'(?<![\w-])(-[A-Za-z]|--[\w-]+)(?=,| <)', line)
                              if line.lstrip().startswith('-') and ' <' in line}

    def is_subcommand(self, word):
        # clap resolves hidden subcommands and aliases here; a prompt word exits non-zero.
        return subprocess.run([self.binary, 'help', word], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=10).returncode == 0


def install_hint(version):
    return f'install it with: npm install -g @openai/codex@{version}'


def official_binary(candidate):
    """Map the PATH `codex` to the executable OpenAI signs.

    npm installs put a Node wrapper on PATH; it runs the binary from the platform package that
    npm selected for this computer, nested or hoisted, or from the package's own vendor tree.
    """
    path = Path(candidate).resolve()
    package = path.parent.parent
    try:
        manifest = json.loads((package/'package.json').read_text())
    except (OSError, ValueError):
        return path
    if path.name != 'codex.js' or manifest.get('name') != '@openai/codex':
        return path
    roots = [package]
    for name in manifest.get('optionalDependencies', {}):
        scope, _, base = name.partition('/')
        roots += [package/'node_modules'/scope/base, package.parent/base]
    found = sorted({exe for root in roots for exe in root.glob('vendor/*/bin/codex') if exe.is_file()})
    if len(found) != 1:
        raise ValueError(f'Cannot find the signed binary inside the npm Codex package at {package}')
    return found[0]


def verify_macos_backend(binary, version):
    """Check public signing metadata before executing a PATH-selected program."""
    try:
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '-R', '='+OFFICIAL_REQUIREMENT,
                        str(binary)], check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f'The macOS backend must be official, OpenAI-signed Codex; {binary} is not; '
                         + install_hint(version)) from exc
    result = subprocess.run([str(binary), '--version'], check=True, capture_output=True,
                            text=True, timeout=10)
    if result.stdout.strip() != 'codex-cli '+version:
        raise ValueError(f'This custom UI requires official Codex {version} on PATH, found '
                         f'{result.stdout.strip() or "no version"}; ' + install_hint(version))


def backend_options(args, cli):
    """Forward invocation config without inspecting configuration or credential contents.

    Returns the backend options, the working directory and the mode: 'session', 'remote-ui'
    or 'utility'.
    """
    options, cwd, command = [], None, None
    profile, remote = False, False
    short = {name for name in cli.value_options if len(name) == 2}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == '--': break
        key, equal, inline = arg.partition('=')
        if key in cli.value_options:
            if equal: value = inline
            elif index+1 < len(args):
                index += 1
                value = args[index]
            else: raise ValueError('Missing value for '+key)
        elif len(arg) > 2 and arg[:2] in short:
            key, value = arg[:2], arg[2:]
        else:
            if not arg.startswith('-') and command is None:
                command = arg if cli.is_subcommand(arg) else 'prompt'
                if command not in SESSIONS | {'prompt'}: break
            index += 1
            continue
        if key in {'-p', '--profile'}:
            profile = True
        if key == '--remote': remote = True
        if key in {'-c', '--config', '--enable', '--disable'}: options.extend([key, value])
        elif key in {'-C', '--cd'}: cwd = Path(value).expanduser().absolute()
        index += 1
    mode = 'utility' if command not in SESSIONS | {'prompt', None} else 'remote-ui' if remote else 'session'
    if profile and mode == 'session':
        raise ValueError('Named --profile selection is not yet supported by the macOS signed backend; use official codex for that profile')
    return options, cwd, mode


def hand_over(command, env):
    """Give the console to `command`: exec on POSIX; run and forward the exit code on Windows.

    Windows cannot replace a process. CPython 3.14's os.execve crashes there, and a working
    one would still return the shell prompt while the TUI kept drawing on the same console.
    """
    if os.name != 'nt':
        os.execve(command[0], command, env)
    # Ctrl-C reaches every process on this console; only the TUI should decide what it means.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    return subprocess.run(command, env=env).returncode


def stop_backend(process):
    # Own only this per-launch process group, never a shared/previous Codex session.
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: return
    try: process.wait(timeout=3)
    except subprocess.TimeoutExpired: pass
    # macOS answers EPERM when every remaining group member is already exiting or a zombie.
    try: os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError): pass
    process.wait()


def run_macos_ui(backend, ui_command, env, options=(), cwd=None, startup_timeout=45):
    import termios
    terminal = termios.tcgetattr(sys.stdin.fileno()) if sys.stdin.isatty() else None
    backend_env = {key: value for key, value in env.items()
                   if key not in {BACKEND_SOCKET, 'CODEX_STATUSLINE_COMMAND'}}
    with tempfile.TemporaryDirectory(prefix='codex-statusline-', dir='/tmp') as temp:
        socket_path = Path(temp)/'app-server.sock'
        backend_process = subprocess.Popen(
            [str(backend), 'app-server', '--listen', 'unix://'+str(socket_path), *options],
            cwd=cwd, env=backend_env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        ui = None
        previous_signals = {}
        def interrupted(signum, frame):
            raise SystemExit(128+signum)
        try:
            for signum in [signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT]:
                previous_signals[signum] = signal.signal(signum, interrupted)
            deadline = time.monotonic()+startup_timeout
            while True:
                if backend_process.poll() is not None:
                    raise ValueError('Official Codex backend exited before startup; custom UI was not started')
                if socket_path.exists():
                    # Upstream advertises a symlink. The native UI verifies its exact
                    # protected endpoint before connecting; this only waits for readiness.
                    info = socket_path.stat()
                    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                        raise ValueError('Invalid private backend socket')
                    break
                if time.monotonic() >= deadline:
                    raise ValueError('Official Codex backend startup timed out; custom UI was not started')
                time.sleep(.02)
            ui_env = dict(env, **{BACKEND_SOCKET: str(socket_path)})
            ui = subprocess.Popen(ui_command, env=ui_env)
            return ui.wait()
        finally:
            if ui is not None and ui.poll() is None:
                ui.terminate()
                try: ui.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    ui.kill()
                    ui.wait()
            stop_backend(backend_process)
            if terminal is not None:
                try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, terminal)
                except OSError: pass
            for signum, handler in previous_signals.items(): signal.signal(signum, handler)


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root/'manifest.json').read_text())
    binary = root/manifest['entrypoint']
    args = sys.argv[1:]
    env = dict(os.environ)
    env['CODEX_STATUSLINE_COMMAND'] = json.dumps([sys.executable, str(root/'codex_statusline.py')])
    if args == ['update']:
        raise SystemExit('Update this patched build with install_codex.py and a new verified bundle; stock Codex updates do not contain the panel.')
    if sys.platform == 'darwin' and args not in [['--version'], ['-V'], ['--help'], ['-h']]:
        try:
            options, cwd, mode = backend_options(args, Cli(binary))
            if mode != 'utility' and (not sys.stdin.isatty() or not sys.stdout.isatty()):
                raise ValueError('Run codex-statusline in a regular interactive terminal')
            if mode == 'remote-ui':
                env.pop(BACKEND_SOCKET, None)
                os.execve(str(binary), [str(binary), '-c', 'check_for_update_on_startup=false', *args], env)
            version = manifest['upstream_version']
            candidate = shutil.which('codex')
            if not candidate: raise ValueError('Official Codex is not on PATH; ' + install_hint(version))
            backend = official_binary(candidate)
            verify_macos_backend(backend, version)
            if mode == 'utility':
                env.pop('CODEX_STATUSLINE_COMMAND', None)
                env.pop(BACKEND_SOCKET, None)
                os.execve(str(backend), [str(backend), *args], env)
            return run_macos_ui(backend, [str(binary), '-c', 'check_for_update_on_startup=false', *args],
                                env, options, cwd)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise SystemExit(str(exc)) from exc
        except KeyboardInterrupt:
            return 130
    return hand_over([str(binary), '-c', 'check_for_update_on_startup=false', *args], env)


if __name__ == '__main__':
    raise SystemExit(main())

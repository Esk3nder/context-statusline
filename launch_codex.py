"""Launch the custom TUI; keep macOS MCP credentials in official signed Codex."""
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

BACKEND_SOCKET = 'CODEX_STATUSLINE_BACKEND_SOCKET'
OFFICIAL_REQUIREMENT = 'identifier "codex" and anchor apple generic and certificate leaf[subject.OU] = "2DC432GLL2"'
UTILITIES = {'exec', 'e', 'review', 'login', 'logout', 'mcp', 'plugin', 'app-server',
             'remote-control', 'app', 'completion', 'doctor', 'sandbox', 'debug',
             'apply', 'a', 'queue', 'archive', 'delete', 'migrate-rollouts', 'migrate-nfs-db',
             'unarchive', 'cloud', 'cloud-tasks', 'exec-server', 'features', 'help',
             'tcp-tunnel', 'execpolicy', 'responses-api-proxy', 'stdio-to-uds', 'agents'}
VALUE_OPTIONS = {'-c', '--config', '--enable', '--disable', '-C', '--cd', '-m', '--model',
                 '-s', '--sandbox', '-a', '--ask-for-approval', '--add-dir', '--local-provider',
                 '--remote', '--remote-auth-token-env', '-p', '--profile', '-i', '--image'}


def verify_macos_backend(binary, version):
    """Check public signing metadata before executing a PATH-selected program."""
    try:
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', '-R', '='+OFFICIAL_REQUIREMENT,
                        str(binary)], check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('The macOS backend must be official, OpenAI-signed Codex on PATH') from exc
    result = subprocess.run([str(binary), '--version'], check=True, capture_output=True,
                            text=True, timeout=10)
    if result.stdout.strip() != 'codex-cli '+version:
        raise ValueError('This custom UI requires official Codex '+version+' on PATH')


def backend_options(args):
    """Forward invocation config without inspecting configuration or credential contents."""
    options, cwd, command = [], None, None
    profile, remote = False, False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == '--': break
        key, equal, inline = arg.partition('=')
        if key in VALUE_OPTIONS:
            if equal: value = inline
            elif index+1 < len(args):
                index += 1
                value = args[index]
            else: raise ValueError('Missing value for '+key)
        elif len(arg) > 2 and arg[:2] in {'-c', '-C', '-m', '-p', '-i', '-s', '-a'}:
            key, value = arg[:2], arg[2:]
        else:
            if not arg.startswith('-') and command is None:
                command = arg if arg in UTILITIES | {'resume', 'fork'} else 'prompt'
                if command in UTILITIES: break
            index += 1
            continue
        if key in {'-p', '--profile'}:
            profile = True
        if key == '--remote': remote = True
        if key in {'-c', '--config', '--enable', '--disable'}: options.extend([key, value])
        elif key in {'-C', '--cd'}: cwd = Path(value).expanduser().absolute()
        index += 1
    if profile and not remote and command not in UTILITIES:
        raise ValueError('Named --profile selection is not yet supported by the macOS signed backend; use official codex for that profile')
    return options, cwd, 'remote-ui' if remote and command not in UTILITIES else None if command == 'prompt' else command


def stop_backend(process):
    # Own only this per-launch process group, never a shared/previous Codex session.
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: return
    try: process.wait(timeout=3)
    except subprocess.TimeoutExpired: pass
    try: os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    process.wait()


def run_macos_ui(backend, ui_command, args, env, startup_timeout=45):
    import termios
    options, cwd, _ = backend_options(args)
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
    binary = root/manifest.get('entrypoint', 'codex.exe' if os.name == 'nt' else 'codex')
    args = sys.argv[1:]
    env = dict(os.environ)
    env['CODEX_STATUSLINE_COMMAND'] = json.dumps([sys.executable, str(root/'codex_statusline.py')])
    if args == ['update']:
        raise SystemExit('Update this patched build with install_codex.py and a new verified bundle; stock Codex updates do not contain the panel.')
    if sys.platform == 'darwin' and args not in [['--version'], ['-V'], ['--help'], ['-h']]:
        try:
            _, _, command = backend_options(args)
            if command not in UTILITIES and (not sys.stdin.isatty() or not sys.stdout.isatty()):
                raise ValueError('Run codex-statusline in a regular interactive terminal')
            if command == 'remote-ui':
                env.pop(BACKEND_SOCKET, None)
                os.execve(str(binary), [str(binary), '-c', 'check_for_update_on_startup=false', *args], env)
            candidate = shutil.which('codex')
            if not candidate: raise ValueError('Install official Codex on PATH before starting the custom macOS UI')
            backend = Path(candidate).resolve()
            verify_macos_backend(backend, manifest['version'].split('-statusline.', 1)[0])
            if command in UTILITIES:
                env.pop('CODEX_STATUSLINE_COMMAND', None)
                env.pop(BACKEND_SOCKET, None)
                os.execve(str(backend), [str(backend), *args], env)
            return run_macos_ui(backend, [str(binary), '-c', 'check_for_update_on_startup=false', *args], args, env)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise SystemExit(str(exc)) from exc
        except KeyboardInterrupt:
            return 130
    os.execve(str(binary), [str(binary), '-c', 'check_for_update_on_startup=false', *args], env)


if __name__ == '__main__':
    raise SystemExit(main())

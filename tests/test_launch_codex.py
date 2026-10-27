import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import launch_codex as launch

VERSION = '1.2.3'
# Excerpt of clap help output: value options carry `<VALUE>`, flags do not.
HELP = '''Usage: codex [OPTIONS] [PROMPT]

Options:
  -c, --config <key=value>
          Override a configuration value. Examples: - `-c model="o3"`
      --enable <FEATURE>
      --disable <FEATURE>
      --remote <ADDR>
      --strict-config
  -i, --image <FILE>...
  -p, --profile <CONFIG_PROFILE_V2>
  -C, --cd <DIR>
      --add-dir <DIR>
      --oss
'''
SUBCOMMANDS = {'resume', 'fork', 'login', 'mcp', 'e', 'execpolicy', 'help', 'agents', 'cloud-tasks',
               'tcp-tunnel', 'responses-api-proxy', 'stdio-to-uds'}


class FakeCli:
    value_options = {'-c', '--config', '--enable', '--disable', '--remote', '-i', '--image',
                     '-p', '--profile', '-C', '--cd', '--add-dir'}

    def is_subcommand(self, word):
        return word in SUBCOMMANDS


def bundle(root, **fields):
    (root/'manifest.json').write_text(json.dumps(
        {'version': VERSION+'-statusline.test', 'upstream_version': VERSION, 'entrypoint': 'bin/codex', **fields}))


class MacBackendTests(unittest.TestCase):
    def test_official_signature_is_verified_before_executing_backend(self):
        with patch('subprocess.run') as run:
            run.side_effect = subprocess.CalledProcessError(1, ['codesign'])
            with self.assertRaisesRegex(ValueError, 'signed'):
                launch.verify_macos_backend(Path('/tmp/untrusted'), VERSION)
            self.assertEqual(run.call_count, 1)
            self.assertIn('/usr/bin/codesign', run.call_args.args[0])

    def test_wrong_backend_version_is_refused(self):
        with patch('subprocess.run') as run:
            run.side_effect = [subprocess.CompletedProcess([], 0, '', ''),
                               subprocess.CompletedProcess([], 0, 'codex-cli 9.9.9\n', '')]
            with self.assertRaisesRegex(ValueError, 'requires official Codex 1.2.3 on PATH, found codex-cli 9.9.9; '
                                        'install it with: npm install -g @openai/codex@1.2.3'):
                launch.verify_macos_backend(Path('/tmp/signed'), VERSION)

    def test_backend_options_preserve_config_and_cwd_without_reading_credentials(self):
        args = ['-C', '/tmp/project with spaces', '-c', 'model="mine"', '--enable', 'thing',
                '--add-dir', '/tmp/other', '--no-daemon', 'resume', '--last']
        options, cwd, mode = launch.backend_options(args, FakeCli())
        # absolute() adds the drive on Windows; the launcher must not resolve symlinks.
        self.assertEqual(cwd, Path('/tmp/project with spaces').absolute())
        self.assertEqual(options, ['-c', 'model="mine"', '--enable', 'thing'])
        self.assertEqual(mode, 'session')
        with self.assertRaisesRegex(ValueError, 'profile'):
            launch.backend_options(['--profile', 'work'], FakeCli())
        self.assertEqual(launch.backend_options(['--', 'login'], FakeCli())[2], 'session')

    def test_subcommands_are_classified_by_the_cli_itself(self):
        cli = FakeCli()
        self.assertEqual(launch.backend_options(['fix', 'the', 'login', 'bug'], cli)[2], 'session')
        options, _, mode = launch.backend_options(['-cmodel=x', 'fork', '--last'], cli)
        self.assertEqual((options, mode), (['-c', 'model=x'], 'session'))
        for word in ['login', 'e', 'execpolicy', 'help']:
            self.assertEqual(launch.backend_options(['-c', 'k=v', word], cli)[2], 'utility')
        # A value is never mistaken for a subcommand.
        self.assertEqual(launch.backend_options(['-C', 'login'], cli)[2], 'session')
        self.assertEqual(launch.backend_options(['--remote', 'unix:///s', 'resume'], cli)[2], 'remote-ui')
        self.assertEqual(launch.backend_options(['--remote', 'unix:///s', 'mcp'], cli)[2], 'utility')

    @unittest.skipUnless(os.name == 'posix', 'shell-script stand-in for the binary')
    def test_cli_surface_is_read_from_the_bundled_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp)/'codex'
            binary.write_text('#!/bin/sh\n'
                              f'[ "$1" = --help ] && {{ cat <<"EOF"\n{HELP}EOF\nexit 0; }}\n'
                              '[ "$1" = help ] && case "$2" in resume|execpolicy|e) exit 0;; esac\n'
                              'exit 2\n')
            binary.chmod(0o755)
            cli = launch.Cli(binary)
            self.assertEqual(cli.value_options, FakeCli.value_options)
            self.assertTrue(cli.is_subcommand('execpolicy'))
            self.assertTrue(cli.is_subcommand('e'))
            self.assertFalse(cli.is_subcommand('fix'))

    def test_npm_wrapper_resolves_to_the_signed_platform_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            modules = Path(temp)/'lib/node_modules'
            package = modules/'@openai/codex'
            (package/'bin').mkdir(parents=True)
            (package/'bin/codex.js').write_text('')
            (package/'package.json').write_text(json.dumps({'name': '@openai/codex', 'optionalDependencies': {
                '@openai/codex-darwin-arm64': '1', '@openai/codex-linux-x64': '1'}}))
            for layout in ['nested', 'hoisted']:
                with self.subTest(layout=layout):
                    root = package/'node_modules/@openai' if layout == 'nested' else modules/'@openai'
                    exe = root/'codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex'
                    exe.parent.mkdir(parents=True)
                    exe.write_text('')
                    link = Path(temp)/'bin/codex'
                    link.parent.mkdir(exist_ok=True)
                    if link.is_symlink(): link.unlink()
                    link.symlink_to(package/'bin/codex.js')
                    self.assertEqual(launch.official_binary(link), exe.resolve())
                    exe.unlink()
            with self.assertRaisesRegex(ValueError, 'signed binary inside the npm Codex package'):
                launch.official_binary(package/'bin/codex.js')
            plain = Path(temp)/'codex'
            plain.write_text('')
            self.assertEqual(launch.official_binary(plain), plain.resolve())

    def test_nonterminal_launch_does_not_start_an_auth_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle(root)
            with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                 patch.object(launch.sys, 'platform', 'darwin'), \
                 patch.object(launch, 'Cli', return_value=FakeCli()), \
                 patch.object(launch.sys, 'argv', ['codex-statusline']), \
                 patch.object(launch.sys.stdin, 'isatty', return_value=False), \
                 patch.object(launch.shutil, 'which', return_value='/tmp/codex'), \
                 patch.object(launch, 'verify_macos_backend') as verify, \
                 patch.object(launch, 'run_macos_ui', return_value=0) as run:
                with self.assertRaisesRegex(SystemExit, 'terminal'):
                    launch.main()
                run.assert_not_called()
                verify.assert_not_called()

    def test_utility_aliases_delegate_to_signed_codex_without_local_backend(self):
        for command in ['cloud-tasks', 'tcp-tunnel', 'execpolicy', 'responses-api-proxy',
                        'stdio-to-uds', 'agents']:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                bundle(root)
                with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                     patch.object(launch.sys, 'platform', 'darwin'), \
                     patch.object(launch, 'Cli', return_value=FakeCli()), \
                     patch.object(launch.sys, 'argv', ['codex-statusline', command, '--help']), \
                     patch.object(launch.sys.stdin, 'isatty', return_value=False), \
                     patch.object(launch.shutil, 'which', return_value='/tmp/official-codex'), \
                     patch.object(launch, 'verify_macos_backend'), \
                     patch.object(launch, 'run_macos_ui') as run, \
                     patch.object(launch.os, 'execve', side_effect=SystemExit(42)) as execute:
                    with self.assertRaises(SystemExit) as result:
                        launch.main()
                    self.assertEqual(result.exception.code, 42)
                    self.assertEqual(Path(execute.call_args.args[0]), Path('/tmp/official-codex').resolve())
                    self.assertNotIn(launch.BACKEND_SOCKET, execute.call_args.args[2])
                    run.assert_not_called()

    def test_explicit_remote_uses_custom_ui_without_starting_local_auth_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle(root)
            with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                 patch.object(launch.sys, 'platform', 'darwin'), \
                 patch.object(launch, 'Cli', return_value=FakeCli()), \
                 patch.object(launch.sys, 'argv', ['codex-statusline', '--remote', 'unix:///tmp/server']), \
                 patch.object(launch.sys.stdin, 'isatty', return_value=True), \
                 patch.object(launch.sys.stdout, 'isatty', return_value=True), \
                 patch.object(launch, 'verify_macos_backend') as verify, \
                 patch.object(launch, 'run_macos_ui') as run, \
                 patch.object(launch.os, 'execve', side_effect=SystemExit(42)) as execute:
                with self.assertRaises(SystemExit) as result:
                    launch.main()
                self.assertEqual(result.exception.code, 42)
                self.assertEqual(Path(execute.call_args.args[0]), root.resolve()/'bin/codex')
                self.assertNotIn(launch.BACKEND_SOCKET, execute.call_args.args[2])
                run.assert_not_called()
                verify.assert_not_called()

    def test_other_platforms_hand_the_console_to_the_bundled_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle(root)
            with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                 patch.object(launch.sys, 'platform', 'win32'), \
                 patch.object(launch.sys, 'argv', ['codex-statusline', '--version']), \
                 patch.object(launch, 'hand_over', return_value=7) as hand_over:
                self.assertEqual(launch.main(), 7)
            command, env = hand_over.call_args.args
            self.assertEqual(Path(command[0]), root.resolve()/'bin/codex')
            self.assertEqual(command[1:], ['-c', 'check_for_update_on_startup=false', '--version'])
            self.assertIn('CODEX_STATUSLINE_COMMAND', env)

    def test_windows_runs_the_binary_and_forwards_its_exit_code(self):
        # Windows has no exec: CPython 3.14's os.execve dies with an access violation there, and
        # even a working one would return the shell prompt while the TUI still owns the console.
        with patch.object(launch.os, 'name', 'nt'), \
             patch.object(launch.os, 'execve') as execute, \
             patch.object(launch.signal, 'signal') as handle, \
             patch.object(launch.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(launch.hand_over(['C:/bundle/codex.exe', '--version'], {'A': '1'}), 7)
        execute.assert_not_called()
        run.assert_called_once_with(['C:/bundle/codex.exe', '--version'], env={'A': '1'})
        handle.assert_called_once_with(signal.SIGINT, signal.SIG_IGN)

    @unittest.skipUnless(os.name == 'posix', 'Unix exec')
    def test_posix_replaces_the_launcher_process(self):
        with patch.object(launch.os, 'execve', side_effect=SystemExit(42)) as execute, \
             patch.object(launch.subprocess, 'run') as run:
            with self.assertRaises(SystemExit):
                launch.hand_over(['/bundle/codex', '--version'], {'A': '1'})
        execute.assert_called_once_with('/bundle/codex', ['/bundle/codex', '--version'], {'A': '1'})
        run.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Unix child lifecycle')
    def test_failed_backend_never_starts_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend = root/'backend'
            backend.write_text('#!/bin/sh\nexit 4\n')
            backend.chmod(0o755)
            marker = root/'ui-started'
            ui = [sys.executable, '-c', f'from pathlib import Path;Path({str(marker)!r}).touch()']
            with self.assertRaisesRegex(ValueError, 'backend'):
                launch.run_macos_ui(backend, ui, os.environ.copy(), startup_timeout=1)
            self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == 'posix', 'Unix socket lifecycle')
    def test_private_backend_lives_only_for_ui_and_cleans_descendants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ticks = root/'ticks'
            backend = root/'backend'
            descendant = f"import time\nf=open({str(ticks)!r},'a')\nfor _ in range(250):\n f.write('x');f.flush();time.sleep(.02)\n"
            backend.write_text('#!'+sys.executable+'\nimport os,socket,subprocess,sys,time\n'
                + f'p=subprocess.Popen([sys.executable,"-c",{descendant!r}])\n'
                + 's=socket.socket(socket.AF_UNIX);s.bind(sys.argv[sys.argv.index("--listen")+1][7:]);s.listen()\n'
                + 'time.sleep(10)\n')
            backend.chmod(0o755)
            captured = root/'ui.json'
            ui_code = ('import json,os,pathlib,stat,time\n'
                'p=pathlib.Path(os.environ["CODEX_STATUSLINE_BACKEND_SOCKET"])\n'
                f'pathlib.Path({str(captured)!r}).write_text(json.dumps([str(p),stat.S_IMODE(p.parent.stat().st_mode)]))\n'
                'time.sleep(.15)\n')
            self.assertEqual(launch.run_macos_ui(backend, [sys.executable, '-c', ui_code],
                                               os.environ.copy(), startup_timeout=2), 0)
            path, mode = json.loads(captured.read_text())
            self.assertEqual(mode, 0o700)
            self.assertFalse(Path(path).exists())
            time.sleep(.1)
            before = ticks.stat().st_size
            time.sleep(.2)
            self.assertEqual(ticks.stat().st_size, before)

    @unittest.skipUnless(os.name == 'posix', 'Unix socket alias')
    def test_official_backend_advertised_socket_alias_reaches_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            backend = root/'backend'
            backend.write_text('#!'+sys.executable+'\nimport os,socket,sys,time\n'
                'p=sys.argv[sys.argv.index("--listen")+1][7:]\n'
                's=socket.socket(socket.AF_UNIX);s.bind(p+".real");s.listen()\n'
                'os.symlink(p+".real",p)\ntime.sleep(10)\n')
            backend.chmod(0o755)
            marker = root/'ui-started'
            code = f'from pathlib import Path;Path({str(marker)!r}).touch()'
            self.assertEqual(launch.run_macos_ui(backend, [sys.executable, '-c', code],
                                                os.environ.copy(), startup_timeout=2), 0)
            self.assertTrue(marker.exists())

    @unittest.skipUnless(os.name == 'posix', 'Unix foreground signals')
    def test_sigquit_cleans_backend_and_descendants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ticks, ready, backend_pid = root/'ticks', root/'ready', root/'backend-pid'
            descendant = f"import time\nf=open({str(ticks)!r},'a')\nfor _ in range(500):\n f.write('x');f.flush();time.sleep(.02)\n"
            backend = root/'backend'
            backend.write_text('#!'+sys.executable+'\nimport os,pathlib,socket,subprocess,sys,time\n'
                + f'pathlib.Path({str(backend_pid)!r}).write_text(str(os.getpid()))\n'
                + f'subprocess.Popen([sys.executable,"-c",{descendant!r}])\n'
                + 's=socket.socket(socket.AF_UNIX);s.bind(sys.argv[sys.argv.index("--listen")+1][7:]);s.listen()\n'
                + 'time.sleep(30)\n')
            backend.chmod(0o755)
            ui_code = f'from pathlib import Path;import time;Path({str(ready)!r}).touch();time.sleep(30)'
            code = ('import launch_codex,os\n'
                    f'launch_codex.run_macos_ui({str(backend)!r},[{sys.executable!r},"-c",{ui_code!r}],os.environ.copy())\n')
            process = subprocess.Popen([sys.executable, '-c', code], start_new_session=True)
            try:
                deadline = time.monotonic()+5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists(), 'test UI did not start')
                os.killpg(process.pid, signal.SIGQUIT)
                process.wait(timeout=5)
                time.sleep(.1)
                before = ticks.stat().st_size
                time.sleep(.2)
                self.assertEqual(ticks.stat().st_size, before, 'backend descendant survived SIGQUIT')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                if backend_pid.exists():
                    try: os.killpg(int(backend_pid.read_text()), signal.SIGKILL)
                    except ProcessLookupError: pass


if __name__ == '__main__':
    unittest.main()

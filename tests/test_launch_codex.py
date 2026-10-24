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


class MacBackendTests(unittest.TestCase):
    def test_official_signature_is_verified_before_executing_backend(self):
        with patch('subprocess.run') as run:
            run.side_effect = subprocess.CalledProcessError(1, ['codesign'])
            with self.assertRaisesRegex(ValueError, 'signed'):
                launch.verify_macos_backend(Path('/tmp/untrusted'), '0.164.0')
            self.assertEqual(run.call_count, 1)
            self.assertIn('/usr/bin/codesign', run.call_args.args[0])

    def test_wrong_backend_version_is_refused(self):
        with patch('subprocess.run') as run:
            run.side_effect = [subprocess.CompletedProcess([], 0, '', ''),
                               subprocess.CompletedProcess([], 0, 'codex-cli 0.165.0\n', '')]
            with self.assertRaisesRegex(ValueError, '0.164.0'):
                launch.verify_macos_backend(Path('/tmp/signed'), '0.164.0')

    def test_backend_options_preserve_config_and_cwd_without_reading_credentials(self):
        args = ['-C', '/tmp/project with spaces', '-c', 'model="mine"', '--enable', 'thing',
                '--add-dir', '/tmp/other', '--no-daemon', 'resume', '--last']
        options, cwd, command = launch.backend_options(args)
        self.assertEqual(cwd, Path('/tmp/project with spaces'))
        self.assertEqual(options, ['-c', 'model="mine"', '--enable', 'thing'])
        self.assertEqual(command, 'resume')
        with self.assertRaisesRegex(ValueError, 'profile'):
            launch.backend_options(['--profile', 'work'])
        self.assertIsNone(launch.backend_options(['--', 'login'])[2])

    def test_nonterminal_launch_does_not_start_an_auth_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'manifest.json').write_text(json.dumps({'version': '0.164.0-statusline.3', 'entrypoint': 'bin/codex'}))
            with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                 patch.object(launch.sys, 'platform', 'darwin'), \
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
                (root/'manifest.json').write_text(json.dumps({'version': '0.164.0-statusline.3'}))
                with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                     patch.object(launch.sys, 'platform', 'darwin'), \
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
            (root/'manifest.json').write_text(json.dumps({'version': '0.164.0-statusline.3'}))
            with patch.object(launch, '__file__', str(root/'launch_codex.py')), \
                 patch.object(launch.sys, 'platform', 'darwin'), \
                 patch.object(launch.sys, 'argv', ['codex-statusline', '--remote', 'unix:///tmp/server']), \
                 patch.object(launch.sys.stdin, 'isatty', return_value=True), \
                 patch.object(launch.sys.stdout, 'isatty', return_value=True), \
                 patch.object(launch, 'verify_macos_backend') as verify, \
                 patch.object(launch, 'run_macos_ui') as run, \
                 patch.object(launch.os, 'execve', side_effect=SystemExit(42)) as execute:
                with self.assertRaises(SystemExit) as result:
                    launch.main()
                self.assertEqual(result.exception.code, 42)
                self.assertEqual(Path(execute.call_args.args[0]), root.resolve()/'codex')
                self.assertNotIn(launch.BACKEND_SOCKET, execute.call_args.args[2])
                run.assert_not_called()
                verify.assert_not_called()

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
                launch.run_macos_ui(backend, ui, [], os.environ.copy(), startup_timeout=1)
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
            self.assertEqual(launch.run_macos_ui(backend, [sys.executable, '-c', ui_code], [],
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
            self.assertEqual(launch.run_macos_ui(backend, [sys.executable, '-c', code], [],
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
                    f'launch_codex.run_macos_ui({str(backend)!r},[{sys.executable!r},"-c",{ui_code!r}],[],os.environ.copy())\n')
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

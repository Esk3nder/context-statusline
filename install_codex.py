#!/usr/bin/env python3
"""Install a verified local Codex statusline bundle alongside stock Codex."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile

APP = 'context-statusline'
RUNTIME = {'codex_statusline.py', 'launch_codex.py', 'context_statusline.py', 'activity.py', 'session_snapshot.py'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _digest(stream)


def _digest(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024*1024), b''):
        result.update(chunk)
    return result.hexdigest()


def verify(bundle):
    if bundle.is_symlink() or (bundle/'manifest.json').is_symlink():
        raise ValueError('Symlinked bundles are refused')
    manifest = json.loads((bundle/'manifest.json').read_text())
    if not isinstance(manifest, dict):
        raise ValueError('Invalid bundle manifest')
    version, files = manifest.get('version'), manifest.get('files')
    binary = 'codex.exe' if os.name == 'nt' else 'codex'
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', version):
        raise ValueError('Invalid bundle version')
    entrypoint = manifest.get('entrypoint', binary)
    if not isinstance(entrypoint, str) or Path(entrypoint).name != binary:
        raise ValueError('Invalid bundle entrypoint')
    if not isinstance(files, dict) or not (RUNTIME | {entrypoint}) <= files.keys() or len(files) > 32:
        raise ValueError('Missing bundle runtime files')
    for name, expected in files.items():
        parts = name.split('/')
        if len(parts) > 4 or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', part) for part in parts) or not isinstance(expected, str):
            raise ValueError('Unsafe manifest entry')
        path = bundle/name
        if any((bundle.joinpath(*parts[:index])).is_symlink() for index in range(1, len(parts)+1)) or not path.is_file() or digest(path) != expected:
            raise ValueError('Bundle verification failed: ' + name)
    return manifest


def paths(prefix):
    prefix = Path(prefix).expanduser().absolute()
    library, bindir = prefix/'lib'/APP, prefix/'bin'
    for path in [prefix, prefix/'lib', library, library/'versions', bindir]:
        if path.is_symlink():
            raise ValueError('Symlinked install directories are refused')
    library.mkdir(parents=True, exist_ok=True)
    bindir.mkdir(parents=True, exist_ok=True)
    launcher = bindir/('codex-statusline.cmd' if os.name == 'nt' else 'codex-statusline')
    if launcher.is_symlink() or (library/'state.json').is_symlink():
        raise ValueError('Symlinked install files are refused')
    state = json.loads((library/'state.json').read_text()) if (library/'state.json').exists() else {}
    if not isinstance(state, dict) or (state and state.get('application') != APP):
        raise ValueError('Unrecognized install state')
    if launcher.exists() and digest(launcher) != state.get('launcher_sha256'):
        raise ValueError('Existing launcher is not owned or has been edited; preserving it')
    return library, launcher, state


def activate(library, launcher, version, state):
    if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', version):
        raise ValueError('Invalid installed version')
    installed = library/'versions'/version
    verify(installed)
    command = [sys.executable, str(installed/'launch_codex.py')]
    if os.name == 'nt':
        # cmd forwards CLI arguments; execution of the renderer itself never uses a shell.
        quoted = ' '.join('\"' + arg.replace('%', '%%') + '\"' for arg in command)
        body = '@echo off\r\nsetlocal DisableDelayedExpansion\r\n' + quoted + ' %*\r\n'
    else:
        body = '#!/bin/sh\nexec ' + shlex.join(command) + ' "$@"\n'
    old = launcher.read_bytes() if launcher.exists() else None
    new_state = {'application': APP, 'current': version, 'previous': state.get('current'),
                 'launcher_sha256': hashlib.sha256(body.encode()).hexdigest()}
    if state.get('current') == version:
        new_state['previous'] = state.get('previous')
    with tempfile.TemporaryDirectory(prefix='.activate-', dir=library) as temp:
        staged = Path(temp)/'launcher'
        staged.write_bytes(body.encode())
        staged.chmod(0o755)
        registry = Path(temp)/'state.json'
        registry.write_text(json.dumps(new_state, indent=2)+'\n')
        staged.replace(launcher)
        try:
            registry.replace(library/'state.json')
        except OSError:
            if old is None: launcher.unlink()
            else: launcher.write_bytes(old)
            raise
    return launcher


def install(bundle, prefix):
    bundle = Path(bundle).absolute()
    manifest = verify(bundle)
    library, launcher, state = paths(prefix)
    versions = library/'versions'
    versions.mkdir(exist_ok=True)
    installed = versions/manifest['version']
    if installed.exists():
        if verify(installed) != manifest:
            raise ValueError('An immutable version already exists with different contents')
    else:
        with tempfile.TemporaryDirectory(prefix='.install-', dir=versions) as temp:
            staged = Path(temp)/'bundle'
            staged.mkdir()
            for name in [*manifest['files'], 'manifest.json']:
                (staged/name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(bundle/name, staged/name, follow_symlinks=False)
            verify(staged)
            for name in manifest['files']:
                executable = Path(name).name.startswith(('codex', 'bwrap', 'rg')) and not name.endswith(('.py', '.json'))
                (staged/name).chmod(0o755 if executable else 0o644)
            staged.rename(installed)
    return activate(library, launcher, manifest['version'], state)


def rollback(prefix):
    library, launcher, state = paths(prefix)
    if not state.get('previous'):
        raise ValueError('No previous installed version')
    return activate(library, launcher, state['previous'], state)


def uninstall(prefix):
    _, launcher, _ = paths(prefix)
    if launcher.exists(): launcher.unlink()
    # Verified version bundles are retained for rollback; no user or stock files are removed.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, nargs='?')
    parser.add_argument('--prefix', type=Path, default=Path.home()/'.local')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--rollback', action='store_true')
    modes.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    try:
        if args.rollback: print(rollback(args.prefix))
        elif args.uninstall: uninstall(args.prefix)
        elif args.bundle: print(install(args.bundle, args.prefix))
        else: parser.error('Provide a local bundle, --rollback or --uninstall')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Installation failed: {exc}\n')


if __name__ == '__main__':
    main()

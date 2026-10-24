#!/usr/bin/env python3
"""Build a pinned, verified Codex patch and package its shared renderer."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=False)


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            result.update(chunk)
    return result.hexdigest()


def normalize_release_lock(source):
    """Upstream release tags bump Cargo.toml but leave workspace lock entries at 0.0.0."""
    workspace = source/'codex-rs'
    match = re.search(r'(?ms)^\[workspace.package\]\s*\nversion = "([^"]+)"', (workspace/'Cargo.toml').read_text())
    if not match:
        raise ValueError('Cannot identify pinned workspace version')
    path = workspace/'Cargo.lock'
    sections = path.read_text().split('\n[[package]]\n')
    for index, section in enumerate(sections):
        if index and '\nsource = ' not in section:
            sections[index] = section.replace('\nversion = "0.0.0"', '\nversion = "'+match[1]+'"', 1)
    path.write_text('\n[[package]]\n'.join(sections))


def prepare(source, metadata):
    patch = ROOT/'codex'/metadata['patch']
    if sha(patch) != metadata['patch_sha256']:
        raise ValueError('Source patch checksum mismatch')
    if not source.exists():
        source.mkdir(parents=True)
        run(['git', 'init', str(source)])
        run(['git', 'remote', 'add', 'origin', metadata['repository']], source)
        run(['git', 'fetch', '--depth', '1', '--no-tags', 'origin', metadata['revision']], source)
        run(['git', 'checkout', '--detach', 'FETCH_HEAD'], source)
    revision = subprocess.check_output(['git','rev-parse','HEAD'], cwd=source, text=True).strip()
    if revision != metadata['revision']:
        raise ValueError('Source does not match pinned Codex revision')
    expected = metadata['patched_files_sha256']
    applied = all((source/name).is_file() and sha(source/name) == value for name,value in expected.items())
    if not applied:
        dirty = subprocess.check_output(['git','status','--porcelain'], cwd=source, text=True)
        if dirty.strip():
            raise ValueError('Source has unexpected changes; use a clean pinned checkout')
        run(['git','apply','--check',str(patch)], source)
        run(['git','apply',str(patch)], source)
    for name, value in expected.items():
        if sha(source/name) != value:
            raise ValueError('Patched source mismatch: '+name)
    changes = subprocess.check_output(['git','diff','--name-only','HEAD'], cwd=source,text=True).splitlines()
    if set(changes) - set(expected) - {'codex-rs/Cargo.lock'}:
        raise ValueError('Unexpected tracked source changes')
    normalize_release_lock(source)


def upstream_helpers(source):
    os.environ['CODEX_REPO_ROOT'] = str(source)
    sys.path.insert(0, str(source/'scripts'))
    from codex_package.targets import TARGET_SPECS
    host = next(line.split(': ', 1)[1] for line in subprocess.check_output(
        ['rustc', '-vV'], cwd=source/'codex-rs', text=True).splitlines() if line.startswith('host: '))
    return TARGET_SPECS[host]


def package(binary_dir, output, metadata, source):
    if output.exists():
        raise ValueError('Output already exists; choose a fresh bundle directory')
    spec = upstream_helpers(source)
    from codex_package.targets import PACKAGE_VARIANTS, PackageInputs
    from codex_package.layout import build_package_dir
    from codex_package.ripgrep import resolve_rg_bin
    suffix = spec.exe_suffix
    inputs = PackageInputs(
        entrypoint_bin=binary_dir/('codex'+suffix),
        code_mode_host_bin=binary_dir/('codex-code-mode-host'+suffix),
        rg_bin=resolve_rg_bin(spec, None),
        bwrap_bin=binary_dir/'bwrap' if spec.is_linux else None,
        codex_command_runner_bin=binary_dir/'codex-command-runner.exe' if spec.is_windows else None,
        codex_windows_sandbox_setup_bin=binary_dir/'codex-windows-sandbox-setup.exe' if spec.is_windows else None)
    output.mkdir(parents=True)
    try:
        build_package_dir(output, metadata['bundle_version'], PACKAGE_VARIANTS['codex'], spec, inputs)
        for name in ['codex_statusline.py','launch_codex.py','context_statusline.py','activity.py','session_snapshot.py']:
            shutil.copy2(ROOT/name, output/name)
        for name in ['UPSTREAM-LICENSE','UPSTREAM-NOTICE']:
            shutil.copy2(ROOT/'codex'/name, output/name)
        files = sorted(p for p in output.rglob('*') if p.is_file())
        manifest = {'version': metadata['bundle_version'], 'upstream_revision': metadata['revision'],
                    'patch_sha256': metadata['patch_sha256'],
                    'entrypoint': 'bin/codex'+suffix,
                    'platform': platform.system().lower()+'-'+platform.machine().lower(),
                    'files': {p.relative_to(output).as_posix():sha(p) for p in files}}
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    except Exception:
        shutil.rmtree(output)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='verify/apply pinned patch without compiling')
    parser.add_argument('--profile', choices=['dev','release'], default='release')
    args = parser.parse_args()
    metadata = json.loads((ROOT/'codex/upstream.json').read_text())
    source = args.source.absolute()
    prepare(source, metadata)
    if args.check: return
    if not args.output: parser.error('--output is required when building')
    spec = upstream_helpers(source)
    from codex_package.v8 import resolve_codex_v8_cargo_env
    build_env = dict(os.environ, **resolve_codex_v8_cargo_env(spec))
    command = ['cargo','build','--locked','--bin','codex','--bin','codex-code-mode-host']
    if sys.platform.startswith('linux'): command += ['--bin','bwrap']
    if os.name == 'nt': command += ['--bin','codex-command-runner','--bin','codex-windows-sandbox-setup']
    if args.profile == 'release': command.append('--release')
    subprocess.run(command, cwd=source/'codex-rs', env=build_env, check=True)
    output = package(source/'codex-rs/target'/('release' if args.profile == 'release' else 'debug'), args.output, metadata, source)
    print(output)


if __name__ == '__main__':
    main()

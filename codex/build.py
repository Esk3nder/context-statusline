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
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from install_codex import RUNTIME  # noqa: E402  (the installer owns the runtime file list)


def run(args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, text=True, capture_output=False)


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            result.update(chunk)
    return result.hexdigest()


def upstream_version(source):
    """The Codex release version, as the pinned source's workspace declares it."""
    match = re.search(r'(?ms)^\[workspace.package\]\s*\nversion = "([^"]+)"', (source/'codex-rs/Cargo.toml').read_text())
    if not match:
        raise ValueError('Cannot identify pinned workspace version')
    return match[1]


def bundle_version(source, metadata):
    """Upstream version plus a digest of everything we add, so no counter is bumped by hand."""
    inputs = hashlib.sha256(metadata['patch_sha256'].encode())
    for name in sorted(RUNTIME):
        inputs.update(name.encode()+b'\0'+(ROOT/name).read_bytes())
    return upstream_version(source)+'-statusline.'+inputs.hexdigest()[:12]


def normalize_release_lock(source):
    """Upstream release tags bump Cargo.toml but leave workspace lock entries at 0.0.0."""
    version = upstream_version(source)
    path = source/'codex-rs/Cargo.lock'
    sections = path.read_text().split('\n[[package]]\n')
    for index, section in enumerate(sections):
        if index and '\nsource = ' not in section:
            sections[index] = section.replace('\nversion = "0.0.0"', '\nversion = "'+version+'"', 1)
    path.write_text('\n[[package]]\n'.join(sections))


def prepare(source, metadata):
    patch = ROOT/'codex'/metadata['patch']
    if sha(patch) != metadata['patch_sha256']:
        raise ValueError('Source patch checksum mismatch')
    if not source.exists():
        source.mkdir(parents=True)
        run(['git', 'init', str(source)])
        run(['git', 'config', 'core.autocrlf', 'false'], source)
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


def package(source, output, metadata, profile):
    """Build with upstream's canonical packager, then add the panel runtime and our manifest.

    The packager owns the cargo targets, helper binaries, ripgrep, V8 setup, stripping and
    layout validation; this script only adds what the panel needs.
    """
    if output.exists():
        raise ValueError('Output already exists; choose a fresh bundle directory')
    version = bundle_version(source, metadata)
    lock = source/'codex-rs/Cargo.lock'
    locked = sha(lock)
    # Upstream's justfile and release workflows export CODEX_REPO_ROOT for the packager.
    env = dict(os.environ, CODEX_REPO_ROOT=str(source))
    try:
        run([sys.executable, str(source/'scripts/build_codex_package.py'), '--variant', 'codex',
             '--package-version', version, '--package-dir', str(output), '--cargo-profile', profile], source, env)
        if sha(lock) != locked:
            raise ValueError('cargo changed Cargo.lock; the pinned dependency set must build as is')
        for name in sorted(RUNTIME):
            shutil.copy2(ROOT/name, output/name)
        for name in ['UPSTREAM-LICENSE','UPSTREAM-NOTICE']:
            shutil.copy2(ROOT/'codex'/name, output/name)
        files = sorted(p for p in output.rglob('*') if p.is_file())
        manifest = {'version': version, 'upstream_version': upstream_version(source),
                    'upstream_revision': metadata['revision'],
                    'patch_sha256': metadata['patch_sha256'],
                    'entrypoint': json.loads((output/'codex-package.json').read_text())['entrypoint'],
                    'executables': [p.relative_to(output).as_posix() for p in files if p.stat().st_mode & stat.S_IXUSR],
                    'platform': platform.system().lower()+'-'+platform.machine().lower(),
                    'files': {p.relative_to(output).as_posix():sha(p) for p in files}}
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='checkout directory; created and fetched at the pinned revision if missing')
    parser.add_argument('--output', type=Path, help='new bundle directory (must not exist)')
    parser.add_argument('--check', action='store_true', help='verify/apply pinned patch without compiling')
    parser.add_argument('--profile', choices=['dev','release'], default='release', help='cargo profile')
    args = parser.parse_args()
    metadata = json.loads((ROOT/'codex/upstream.json').read_text())
    source = args.source.absolute()
    prepare(source, metadata)
    if args.check: return
    if not args.output: parser.error('--output is required when building')
    print(package(source, args.output.absolute(), metadata, args.profile))


if __name__ == '__main__':
    main()

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


def package(binary_dir, output, metadata):
    if output.exists():
        raise ValueError('Output already exists; choose a fresh bundle directory')
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = ['codex', 'codex-code-mode-host', 'codex-responses-api-proxy']
    if sys.platform.startswith('linux'): binaries.append('bwrap')
    required = [(binary_dir/(name+suffix), name+suffix) for name in binaries]
    required += [(ROOT/name, name) for name in ['codex_statusline.py','launch_codex.py',
                  'context_statusline.py','activity.py','session_snapshot.py']]
    required += [(ROOT/'codex'/'UPSTREAM-LICENSE', 'UPSTREAM-LICENSE'),
                 (ROOT/'codex'/'UPSTREAM-NOTICE', 'UPSTREAM-NOTICE')]
    if any(not path.is_file() for path,_ in required):
        raise ValueError('Missing build output or runtime/license file')
    output.mkdir(parents=True)
    try:
        for path,name in required: shutil.copy2(path, output/name)
        manifest = {'version': metadata['bundle_version'], 'upstream_revision': metadata['revision'],
                    'patch_sha256': metadata['patch_sha256'],
                    'platform': platform.system().lower()+'-'+platform.machine().lower(),
                    'files': {name:sha(output/name) for _,name in required}}
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
    command = ['cargo','build','--locked','--bin','codex','--bin','codex-code-mode-host','--bin','codex-responses-api-proxy']
    if sys.platform.startswith('linux'): command += ['--bin','bwrap']
    if args.profile == 'release': command.append('--release')
    run(command, source/'codex-rs')
    output = package(source/'codex-rs/target'/('release' if args.profile == 'release' else 'debug'), args.output, metadata)
    print(output)


if __name__ == '__main__':
    main()

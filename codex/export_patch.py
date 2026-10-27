#!/usr/bin/env python3
"""Export the Codex TUI patch and its checksums from a prepared source checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK = 'codex-rs/Cargo.lock'


def git(source, *args):
    return subprocess.check_output(['git', '-c', 'core.quotepath=false', *args], cwd=source)


def export(source, metadata):
    """Return the patch bytes and per-file checksums for every tracked change in `source`.

    The lock file travels in the patch (the build needs its dependency entries) but is excluded
    from the checksum manifest because build.py normalizes release versions inside it.
    """
    revision = git(source, 'rev-parse', 'HEAD').decode().strip()
    if revision != metadata['revision']:
        raise ValueError('Source does not match pinned Codex revision')
    patch = git(source, 'diff', '--binary', '--no-color', '--no-ext-diff', 'HEAD')
    names = git(source, 'diff', '--name-only', 'HEAD').decode().splitlines()
    hashes = {}
    for name in sorted(names):
        path = source/name
        if name != LOCK and path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return patch, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='patched checkout of the pinned revision')
    args = parser.parse_args()
    metadata_path = ROOT/'codex/upstream.json'
    metadata = json.loads(metadata_path.read_text())
    patch, hashes = export(args.source.absolute(), metadata)
    (ROOT/'codex'/metadata['patch']).write_bytes(patch)
    metadata['patch_sha256'] = hashlib.sha256(patch).hexdigest()
    metadata['patched_files_sha256'] = hashes
    metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
    print(f"{metadata['patch']}: {len(hashes)} files, sha256 {metadata['patch_sha256']}")


if __name__ == '__main__':
    main()

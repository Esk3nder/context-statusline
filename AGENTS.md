# Agent Instructions

```yaml
last_updated: 2026-10-25
owner: repository maintainer
revalidate_when:
  - test or CI commands change
  - runtime files or installers change
  - the pinned Codex revision or packaging flow changes
```

A wide statusline for Claude Code (`context-bar.sh` → `context_statusline.py`) and the
same panel inside a patched Codex CLI (`codex/`, `install_codex.py`, `launch_codex.py`).
User-facing install steps live in `README.md`; do not repeat them here.

## Checks

Run these before calling a change done. CI runs the same list (`.github/workflows/test.yml`).

```bash
python3 -m unittest discover -s tests -v
bash -n context-bar.sh
git ls-files -z '*.py' | xargs -0 python3 -m py_compile
python3 docs/examples/render.py && git diff --exit-code -- docs/examples
```

The native Codex build (`.github/workflows/codex-native.yml`) compiles Rust and takes about
two hours per OS. Run it locally only when the patch or packaging changes; see
`README.md` → "Build from source".

## Generated files: never edit by hand

- `docs/examples/*.svg`, `preview.txt`: run `python3 docs/examples/render.py`.
- `codex/native-statusline.patch` and the checksums in `codex/upstream.json`: edit the
  TUI in a checkout of the pinned revision, then run `python3 codex/export_patch.py --source <checkout>`.

## Sources of truth: derive, do not copy

- Codex version: the pinned source's `codex-rs/Cargo.toml`. Rust toolchain: its
  `codex-rs/rust-toolchain.toml`. `codex/upstream.json` pins only the commit and checksums.
- Bundle version: computed by `codex/build.py` from the upstream version plus a digest of the
  patch and runtime files. There is no counter to bump.
- Codex subcommands and value options: read from the bundled binary at launch (`launch_codex.Cli`).
- Bundle runtime file list: `install_codex.RUNTIME`. Codex package layout: upstream's
  `scripts/build_codex_package.py`.
- Claude settings entries: `context_statusline.settings_fragment()`; `install_claude.py` applies them.

## Invariants

- No network access, daemons or credentials at statusline runtime; Python 3.9+ standard library only.
- Observer hooks record metadata only and never block, allow or deny a tool call.
- Missing data renders as unavailable, never as a confident zero.
- Installers change only what they own: `install_claude.py` touches only its own settings
  entries; `install_codex.py` never touches stock `codex`, its config or its credentials.
- On macOS the Codex UI never falls back to its unsigned embedded backend.

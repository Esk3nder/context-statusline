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

## Updating upstream Codex

Move to the newest **stable** release. Skip `-alpha`/`-beta` tags. Do not write a version
number into any file; the version comes from the pinned source.

1. Find the latest stable release (the peeled tag line gives the commit):

   ```bash
   git ls-remote --tags https://github.com/openai/codex.git 'refs/tags/rust-v*' | awk '{print $2}' | sed -n 's#^refs/tags/rust-v\([0-9][0-9.]*[0-9]\)$#\1#p' | sort -V | tail -1
   ```

   If it matches `[workspace.package] version` in the pinned checkout's `codex-rs/Cargo.toml`, stop: nothing to update.
2. Set `revision` in `codex/upstream.json` to that commit. Change nothing else yet.
3. Run `python3 codex/build.py --source <checkout> --check` with a checkout outside this repo. It fetches the commit and applies the patch. If `git apply --check` fails, port each changed hunk of `codex/native-statusline.patch` into the checkout by hand, resolving it against the new source.
4. Regenerate the patch and checksums: `python3 codex/export_patch.py --source <checkout>`. Then rerun the `--check` command; it must pass without applying anything.
5. Build and test the Rust side in the checkout: `rustup toolchain install` in `codex-rs`, then `cargo test -p codex-tui --lib context_statusline`. Run `cargo test -p codex-tui` too. Upstream's `safety_buffering` pair can fail when run in one process, but each passes alone. Inspect every snapshot change. Accept only changes the upstream release causes, such as version strings. Never accept a snapshot to make a test pass. Rerun step 4 after any snapshot change, because snapshots are in the patch.
6. Run the repo checks above, then build a local bundle into a new empty directory, install it to a temporary prefix, and run `codex-statusline --version`. On macOS, also run a PTY smoke test with official Codex at the new version on PATH.
7. Commit `codex/upstream.json`, `codex/native-statusline.patch` and any code or test changes together. Push to the PR branch. Do not merge until `Test` and `Native Codex bundle` pass on all three operating systems.

Stop and report before continuing if the port needs a change to `launch_codex.py` or `install_codex.py`
(the Codex command surface or signing requirement changed), or if upstream removed an app-server
interface the panel uses. Publishing a release is a separate, authorized action.

## Invariants

- No network access, daemons or credentials at statusline runtime; Python 3.9+ standard library only.
- Observer hooks record metadata only and never block, allow or deny a tool call.
- Missing data renders as unavailable, never as a confident zero.
- Installers change only what they own: `install_claude.py` touches only its own settings
  entries; `install_codex.py` never touches stock `codex`, its config or its credentials.
- On macOS the Codex UI never falls back to its unsigned embedded backend.

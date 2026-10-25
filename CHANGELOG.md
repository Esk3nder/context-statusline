# Changelog

## Unreleased

### Added
- One wide personal layout with neutral text hierarchy, bold current tasks and native elapsed session time.
- Full wrapping native task checklist, with confirmed legacy to-do fallback and explicit incomplete-data notices.
- Bounded discovered configuration counts, successful skill/MCP usage, and main/subagent file-target metadata.
- Context/quota/cost instrument layout with responsive widths and plain/ASCII output.
- Native agent row formatter and optional private, observer-only activity cache.
- Event-based notices and diagnostics that leave unsupported forecasts unavailable.
- Regression tests and Python/macOS/Linux CI.
- `install_claude.py`: one command adds the statusline (and, with `--observers`, the activity hooks) to Claude Code settings, with `--dry-run`, a backup, `--replace` for another tool's statusline, and `--uninstall` that removes only its own entries.
- `codex-statusline`: the same panel inside a patched Codex CLI built from a pinned upstream commit, with a verified installer/launcher, reproducible patch export (`codex/export_patch.py`) and a native bundle workflow. Versions are derived, not written down: the Codex version comes from the pinned source, the bundle version adds a digest of our inputs, and the launcher reads Codex's command and option surface from the bundled binary. The build uses upstream's own packager and layout validation. On macOS an npm-installed official Codex is accepted, and every failed check names the fix. On Windows the launcher runs the bundled binary and forwards its exit code instead of `exec`, which Windows cannot do.

### Fixed
- Use the supplied session cost estimate instead of repricing context tokens.
- Preserve unknown metrics instead of displaying false zeroes.
- Treat model labels as text, remove terminal control sequences, and respect host width without touching `/dev/tty`.
- Readable on light terminal themes: text follows the terminal foreground; meter fills use mid tones with at least 3:1 contrast on white and near-black; alerts color only their `!` marker.
- Fit inside Claude's footer spacing (`COLUMNS` less four cells) instead of overflowing into `…`.
- Name the repository that owns the displayed branch, not the folder where the session started.
- Omit zero configuration counts and name hook counts as `hooks on N events`.

### Changed
- Requires Python 3.9+ instead of `jq`. Install all four runtime files together; `context-bar.sh` remains the entry point.
- Percentages show actual supplied usage; legacy compaction-threshold scaling is ignored.

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

### Fixed
- Use the supplied session cost estimate instead of repricing context tokens.
- Preserve unknown metrics instead of displaying false zeroes.
- Treat model labels as text, remove terminal control sequences, and respect host width without touching `/dev/tty`.
- Readable on light terminal themes: text follows the terminal foreground; meter fills use mid tones with at least 3:1 contrast on white and near-black; alerts color only their `!` marker.
- Fit inside Claude's footer spacing (`COLUMNS` less four cells) instead of overflowing into `…`.
- Name the repository that owns the displayed branch, not the folder where the session started.
- Omit zero configuration counts and name hook counts as `hooks on N events`.

### Changed
- Requires Python 3.10+ instead of `jq`. Install all four runtime files together; `context-bar.sh` remains the entry point.
- Percentages show actual supplied usage; legacy compaction-threshold scaling is ignored.

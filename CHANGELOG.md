# Changelog

## Unreleased

### Added
- Context/quota/cost instrument layout with responsive widths and plain/ASCII output.
- Native agent row formatter and optional private, observer-only activity cache.
- Event-based notices and diagnostics that leave unsupported forecasts unavailable.
- Regression tests and Python/macOS/Linux CI.

### Fixed
- Use the supplied session cost estimate instead of repricing context tokens.
- Preserve unknown metrics instead of displaying false zeroes.
- Treat model labels as text, remove terminal control sequences, and respect host width without touching `/dev/tty`.

### Changed
- Requires Python 3.10+ instead of `jq`. Install all three runtime files together; `context-bar.sh` remains the entry point.
- Percentages show actual supplied usage; legacy compaction-threshold scaling is ignored.

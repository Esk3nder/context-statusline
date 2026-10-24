# Instrument Statusline Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the approved instrument display and evidence-based agent activity rows.
**Architecture:** Python standard-library renderer behind the existing Bash entry point, native subagent JSONL formatter, and optional private observer cache.
**Tech Stack:** Python 3.10+, Bash, SQLite, unittest.
**Spec:** docs/superpowers/specs/2026-10-23-instrument-statusline-design.md

## Global Constraints

No external packages/network/daemon/transcript reads. Preserve missing vs zero; sanitize terminal text; honor COLUMNS and native columns. Only documented fields and exact ID correlation. Observer stdout is empty and never makes a permission decision. Preserve current live configuration.

## Review Focus

Malformed/null/nonfinite metrics; control characters and wide Unicode; expired quota windows; concurrent and unrelated session events; stale or mismatched agent IDs. Add cases to the owning task.

### Task 1: Main instrument renderer

Files: `context_statusline.py`, `context-bar.sh`, `tests/test_statusline.py`, `tests/fixtures/session.json`.
Interfaces: `render_main(data, width, color, ascii_mode, now)` returns rendered text; `main()` consumes JSON stdin.
- [x] Write tests for supplied $12.34 overriding token repricing, zero vs missing, expired/binding quotas, invalid JSON, terminal escape labels, and widths 12/24/44/72/100.
- [x] Run `python3 -m unittest discover -s tests -v`; observe failures against the old entry point.
- [x] Implement main renderer and compatibility entry point; use remaining context only when percentage and size are supplied.
- [x] Run full unittest suite and `bash -n context-bar.sh`; expect pass.
- [x] Commit main renderer and tests.

### Task 2: Native agent formatting and observer state

Files: `context_statusline.py`, `tests/test_activity.py`, `tests/fixtures/subagents.json`.
Interfaces: `render_subagents(data, width, color, ascii_mode, now)` returns JSONL rows; `observe(data, now)` updates bounded session-local metadata; `load_state(session_id, now)` returns valid cache or empty state.
- [x] Write tests for native IDs/statuses, running vs completed elapsed, exact hook/task ID matching, Pre/PostToolUse pending lifecycle, permission-event wording, quiet tool calls, concurrent writers, expiry, session isolation, cache symlinks, and secret minimization.
- [x] Run new tests; expect missing capability failures.
- [x] Implement optional observer, native JSONL, evidence-only diagnostics and settings-fragment output.
- [x] Run full suite; expect pass; benchmark representative redraws.
- [x] Commit agent activity slice.

### Task 3: Distribution and reviewable examples

Files: `README.md`, `CHANGELOG.md`, `.gitignore`, `docs/examples/`, optional CI configuration.
Interfaces: existing entry-point path remains supported; documented settings fragment contains only additive, observer-only hooks.
- [x] Document two-file installation, settings merge, Python dependency, native panel placement, optional activity data, source/version boundaries and rollback.
- [x] Generate fixtures and examples by executing the real renderer; no hand-drawn output in README.
- [x] Run full tests, syntax checks and available linters; inspect staged diff and independently review the branch.
- [x] Address important findings, commit, and provide the feature branch/review artifact. Do not replace live Auto configuration or merge main.

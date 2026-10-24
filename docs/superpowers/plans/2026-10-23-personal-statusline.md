# Personal statusline implementation plan

Spec: docs/superpowers/specs/2026-10-23-personal-statusline-design.md
Base: 68eb1c1; existing isolated feature/instrument-statusline worktree. Execute inline, one final independent review. Approval is the user's “ok lets build it” after the wide neutral preview.

## Global constraints

Standard-library Python 3.10+, no network/daemon/transcript parsing, no live settings mutation. All new files installed beside the wrapper. Unknown/partial data stays explicit; retain prior safety/regression behavior except superseded visual/session-time assertions.

### Task 1: Local snapshots

Files: new session_snapshot.py and tests/test_snapshot.py.
Interfaces: config_snapshot(cwd, config_dir=None, home=None) -> counts dict; task_snapshot(session_id, config_dir=None, list_id=None) -> {available: bool, tasks: [{id,subject,status}], partial: bool}. Directory/config limits and unsafe-path handling follow spec. Read task files afresh each render to follow updates and resumed/shared lists.
Steps: executable/unit tests first for exact task identity/status, updates/deletion, explicit empty native list, shared list, traversal/symlinks, malformed/oversized JSON, config scope deduplication and disabled MCP handling. Observe RED for missing module, implement bounded readers, then GREEN full suite. Commit.
Expected: python3 -m unittest discover -s tests -v exits 0.

### Task 2: Observed activity

Files: activity.py and tests/test_activity.py; new helper functions may remain private to activity.py.
Interfaces: record.pending[hashed_call] adds optional target basename; state.used.skills / state.used.mcps hold bounded successful invocation names; each record.todos holds sanitized confirmed TodoWrite items. Preserve native ID/session boundaries and observer silence. Add SessionStart (no fabricated start clock) to event list for lifecycle coverage if needed by state initialization; native duration remains authoritative.
Steps: tests first for main/child targets, basename-only persistence, confirmed legacy tasks vs failed calls, used skill/MCP metadata, agent task isolation and reset; observe RED, implement allowlists, GREEN full suite. Commit.
Expected: full suite exits 0 and no raw input/result/command retention.

### Task 3: Layout and delivery

Files: context_statusline.py, tests/test_statusline.py, docs/examples/render.py + outputs, README.md, CHANGELOG.md, CI compilation list.
Interfaces: render_main(..., snapshot=None) consumes configuration/tasks snapshots; CLI gathers snapshots only in main/diagnostics modes. Add whitespace-aware cell wrapping to task/activity/config bands; preserve paint as the hard width boundary. Use native duration in identity, neutral styles except meter/alerts, main activity from @main, task native precedence over observed legacy. render_subagents consumes target metadata on exact ID match. Keep JSONL and diagnostics strict JSON.
Steps: failing tests for session duration, neutral primary text, task completion count and full wrapped subjects at 128/100/72/44 widths, malformed data and absent-band behavior. Implement, full suite. Generate examples with synthetic snapshots and observer state; expose 128-column default while retaining 100/72/44 fixtures. Update migration/install/privacy docs. Verify Bash/Python syntax, ShellCheck, deterministic generation, diff check, redraw benchmark; one independent final review, fix important findings RED→GREEN, update PR and CI, replace browser prototype with actual output. Commit/push feature only.
Expected: full suite and CI pass; browser has aligned actual meters and approved neutral hierarchy.

## Review focus

1. Task list selection/traversal and authoritative-empty native list versus legacy fallback.
2. New metadata must never retain arbitrary commands/results or mix agent sessions.
3. Bounded config discovery must report partial scans and avoid symlink cycles.
4. Narrow Unicode wrapping must terminate without clipping task subjects or exceeding width.
5. Runtime examples must use injected synthetic snapshots and never scan the author's real configuration.

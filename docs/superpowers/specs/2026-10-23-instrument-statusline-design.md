# Instrument statusline

Approved basis: the user's final screenshot, October 23, 2026. Keep project/branch and model/effort above three instruments: context usage with remaining tokens, quota usage/reset, and the supplied session cost estimate. Both meters use blocks; context retains the green-to-rose gradient. Agent rows show role, reported state and elapsed time; optional observer metadata adds last event and pending tool result. No default sparklines or session-duration instrument.

## Approach and boundaries

Use the documented main `statusLine` and separate native `subagentStatusLine` surfaces. Claude owns the agent panel's placement and tree markers. A small optional observer records event metadata; it never returns decisions. A standalone Python 3.10+ standard-library renderer handles JSON, Unicode width, bounded input and a private SQLite activity cache. Keep `context-bar.sh` as the entry point. This replaces the Bash/jq implementation because validated JSON, concurrent event updates and terminal sanitization would otherwise require multiple ad hoc shell protocols. No external packages, network requests, daemon, transcript reading, or model calls.

Use native task IDs; correlate hook `agent_id` only on exact equality. Never guess by role/name. PreToolUse does not prove execution: say `tool result pending`. PermissionRequest does not establish that a prompt is still waiting: show a recent `approval requested` event, not an enduring current-permission claim. Completed tasks have an elapsed duration only when a matching stop event supplies an end time. Missing metrics remain unavailable; zero remains zero.

Main view emphasizes current context >=85% and quota >=90%, without forecasting compaction. Select the more-used available five-hour/seven-day quota window; ignore expired windows. A recorded compaction can show briefly, without inferred reclaimed tokens or memory quality. Diagnostics report evidence and unavailable forecasts, not invented estimates. Codex does not execute this renderer through its native footer picker; document that boundary.

## Trust and persistence

Sanitize all externally supplied labels, including terminal escapes and bidi controls. Limit input to 1 MiB, tasks to 64, and displayed output to the host width. Store only IDs, role, event/tool names, timestamps and bounded pending-call metadata; never tool inputs/results, prompts, transcripts, summaries or credentials. Cache directory 0700, database 0600, refuse symlinks and foreign ownership, short SQLite lock timeout. Isolate sessions by a hashed key; prune records after 24h and clear a session on SessionEnd. Observer errors must not block Claude.

## Delivery

Implement and test in a feature worktree; preserve the existing Auto-generated live statusline until a replacement is ready and explicitly selected. Provide a settings fragment that can be merged without replacing existing hooks, fixtures, documentation and actual rendered examples. No automatic global configuration change or main-branch merge.

## Sources checked October 23, 2026

- https://code.claude.com/docs/en/statusline#available-data
- https://code.claude.com/docs/en/statusline#subagent-status-lines
- https://code.claude.com/docs/en/hooks#common-input-fields
- https://code.claude.com/docs/en/hooks#pretooluse
- https://code.claude.com/docs/en/hooks#permissionrequest
- https://code.claude.com/docs/en/hooks#postcompact

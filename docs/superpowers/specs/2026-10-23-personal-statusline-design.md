# Eskender's personal statusline

Approved October 23, 2026 after browser review: one opinionated wide layout, neutral text, no modes or theme controls. Supersedes the earlier design's exclusion of elapsed time and selective task/tool metadata. Keep the existing feature branch and draft PR; do not change Auto-managed live configuration or merge main.

## Display

At 128 columns: project/branch left; model, effort and supplied elapsed session time right. Directory and discovered configuration form a quiet second band. Three aligned instruments retain the gradient context block meter, solid quota block meter and supplied cost estimate. Primary values/current work are off-white; secondary labels and pending work readable grey; completed work dim grey. Only meters and conditional attention rows use color.

The lower bands show main tool metadata, the complete checklist flowing horizontally and wrapping by terminal cells, observed skill/MCP names, and native subagent activity. Empty evidence-based bands disappear. Completed checklist items come first; current/pending items follow with symbols. Preserve every supported task subject, wrapping long titles instead of clipping. A bounded input notice discloses incomplete lists. There is one layout; narrower terminals wrap the same information in the same order, grouping instruments as width permits.

Claude owns placement of its separate native agent panel. Each JSONL agent row shows role, native state and elapsed time, then its exact-ID-correlated tool target and pending-result age when available. Never claim a pending request is executing or stalled.

## Sources and privacy

Use native stdin for context, quota, cost, effort and cost.total_duration_ms (elapsed wall time including idle). Read Claude's documented ~/.claude/tasks/<list-id>/ directory for Task-tool state, honoring CLAUDE_CONFIG_DIR and CLAUDE_CODE_TASK_LIST_ID. JSON id/subject/status is a version-sensitive adapter, not a promised public file schema: validate each record, reject unsafe paths/symlinks, limit to 256 files and 64 KiB per JSON file, and disclose partial/unsupported data. Read titles and statuses only for display; do not copy task files/descriptions into the observer cache. A confirmed PostToolUse TodoWrite can supply a sanitized legacy fallback when no native list exists. Native lists take precedence, including an empty list.

Scan only known user/project instruction/config locations and bounded rule directories. Counts describe discovered instruction/rule files, configured MCP names and hook event categories, not loaded context or server liveness. Deduplicate physical instruction/rule files and MCP names; project/local disabled entries remove configured MCP names. Never execute config or expand arbitrary imports, never print settings values or credentials. Bound scans and disclose partial results.

Extend observer metadata to retain sanitized file basenames for known file tools, skill identifiers, and MCP names. Never store Bash commands, file contents, search patterns, raw tool responses, arbitrary inputs, prompts, transcripts or compaction summaries. A failed call must not mutate legacy task state or mark a skill/MCP successfully used. Keep session isolation, exact agent IDs, private SQLite permissions, 24h retention, and fail-open silence. SubagentStop clears pending calls. Legacy task state belongs to its observed agent; only main-session tasks enter the main checklist.

## Validation and delivery

Synthetic native task/config fixtures prove updates/deletion/resume/shared-list selection, traversal/symlink rejection, malformed/oversized data, deduplication and disabled MCP handling. Executable tests prove main/subagent tool correlation, privacy, failed-call behavior, neutral text, complete wrapping checklists and Unicode width. Regenerate actual-renderer examples at 128/100/72/44 columns, browser-check alignment, benchmark redraws, independent final review, and Linux/macOS CI. No network or new packages at runtime. Keep all runtime files together; update install/migration/privacy docs.

## Sources verified

- https://code.claude.com/docs/en/statusline
- https://code.claude.com/docs/en/hooks#posttooluse
- https://code.claude.com/docs/en/hooks#common-input-fields
- https://code.claude.com/docs/en/interactive-mode#task-list

# Context Statusline

An opinionated, wide statusline for Claude Code. Keep the current task, main and delegated tool activity, configuration, context, quota and estimated cost in view. One layout: bright current work, quiet supporting detail, and color reserved for meters and attention.

![Fixture output from the actual renderer](docs/examples/preview.svg)

*Generated from synthetic inputs by the actual renderer. The main footer and native agent panel are shown together for reference; Claude controls their placement.*

## Install

Requires **Python 3.10+**, Bash, and Claude Code. No `jq`, pip packages, daemon, API keys or network calls are needed at runtime. macOS and Linux are supported.

```bash
git clone https://github.com/Esk3nder/context-statusline.git ~/.claude/context-statusline
~/.claude/context-statusline/context-bar.sh --settings
```

The second command prints a configuration fragment pointing at your checkout. It **does not edit your settings**. Keep the checkout together: `context-bar.sh`, `context_statusline.py`, `activity.py` and `session_snapshot.py` are the four runtime files. Keep all four together.

Back up `~/.claude/settings.json`, then merge the generated `statusLine` and `subagentStatusLine` entries into it. A minimal example, without activity observers:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/context-statusline/context-bar.sh",
    "refreshInterval": 5
  },
  "subagentStatusLine": {
    "type": "command",
    "command": "~/.claude/context-statusline/context-bar.sh --subagents"
  }
}
```

Claude reloads saved settings. Keep any unrelated settings and hooks. If another application manages your statusline, configure the replacement there or it may overwrite this change.

### Optional activity observers

To add main/subagent tool targets, observed skill/MCP usage and legacy to-do tracking, append the hook groups printed by `--settings` to the corresponding arrays in your existing `hooks` object. **Do not replace existing hook arrays.** The generated commands record metadata only; they never allow, deny or block a tool call.

The observers cover tool requests/results/failures, permission events, subagent start/stop, compaction completion and session end. They retain IDs, timestamps, tool/event names, sanitized file basenames for known file tools, successful skill/MCP names, and confirmed legacy `TodoWrite` titles/statuses in a private local SQLite cache. They never store commands, file contents, search patterns, raw tool inputs/results, task descriptions, prompts, transcripts, compaction summaries or credentials. No transcript files are opened. Records expire after 24 hours, are pruned on the next observer write, and are removed for a session on `SessionEnd`.

Default cache: `~/.cache/context-statusline/activity.sqlite3`. `CONTEXT_STATUSLINE_STATE_DIR` can select another private directory. The directory must be owned by you with mode `0700`; database files must have mode `0600`. Symlinks are refused. Observer errors fail open and emit no hook decisions. A 200 ms SQLite lock budget keeps hooks bounded; observations are best effort under extreme writer contention.

Native task IDs are matched to hook `agent_id` values **only on exact equality**. If a host version uses different IDs, the row still shows native state, but activity details are omitted. No correlation by name or role is attempted.

## What the display means

- **Context:** the supplied percentage used, plus remaining tokens calculated from that percentage and the supplied context-window size. This is nominal capacity, not a quality score or a prediction of compaction.
- **Quota:** the more-used available five-hour or seven-day account window. Expired windows are ignored. API accounts or new sessions may not supply a window; the display says unavailable.
- **Cost:** Claude's supplied `cost.total_cost_usd`, labeled as a session estimate. It is not recalculated from token counts or presented as a bill. This tool does not split main-agent and delegated costs or make an independent claim about their inclusion.
- **Agents:** Claude's reported state. `completed` is not verified success. Running elapsed time comes from native `startTime`; completed duration appears only with a matching observed stop event.
- **Session:** `cost.total_duration_ms`, displayed in the header as elapsed wall time including idle. Missing/invalid duration is omitted.
- **Configuration:** discovered `CLAUDE.md`/`CLAUDE.local.md` files, `.claude/rules/*.md` files (including nested directories), configured MCP names, and hook event categories from known user and project/ancestor config locations. Counts deduplicate physical files and MCP names and apply explicit disabled MCP entries. These are discovered configuration counts, not a claim that files are loaded or servers connected. Managed/plugin configuration is not comprehensively enumerated.
- **Used:** successful skill and MCP invocations observed in this session, including matching child events. Installed/available skills are not presented as used.
- **Activity:** time since the observer received an event. `Read main.py · awaiting result` means the observer has a request without a matching result. The displayed time is the age of that request. It does not prove the tool is executing or stalled. A quiet tool does not trigger an inactivity warning.

The agent panel has its own documented `subagentStatusLine` JSONL interface; it is not part of the main footer's stdin payload. Native `agentType` requires Claude Code **2.1.293+**; older payloads fall back to a supplied name. Keep Claude current for both statusline surfaces.

## Claude’s task list

The checklist reads `~/.claude/tasks/<session_id>/*.json` on each render. `CLAUDE_CONFIG_DIR` changes the config root and `CLAUDE_CODE_TASK_LIST_ID` selects a named shared list, matching Claude’s documented task directory. Tasks survive restarts/compaction because this reads their current files; updates and deletions are reflected on the next repaint. An existing empty native list clears the display and takes precedence over legacy observer data.

The directory is documented; individual JSON records are a **version-sensitive adapter**, validated as `{id, subject, status}` with `pending`, `in_progress` or `completed` status. Unsupported, malformed or unreadable records produce `Task list incomplete`; no IDs are guessed. If no native list exists, successful `PostToolUse` events for main-session `TodoWrite` provide a legacy fallback. Rejected or unreadable native lists report incomplete data instead of showing cached legacy tasks. Child task lists never enter the main checklist. Task-tool availability depends on the host/model; this package does not enable tools or manufacture a list.

The whole supported list flows across the width: completed items recede, the current task is bright/bold, and pending items remain readable. Long titles wrap. It is display-only, with no layout modes or editable checkboxes. Safety bounds are 256 task files, 64 KiB per JSON file, 512 characters per title and 2,000 directory entries. Incomplete/bounded data is disclosed. Native task files and descriptions are never copied into our cache; only titles/statuses enter the display/diagnostics. Symlinked task roots/lists/files and traversal in list IDs are refused.

Configuration discovery also has a 2,000-entry rule budget, 32-ancestor limit and 1 MiB configuration JSON limit (task files remain capped at 64 KiB). Symlinked rule directories are skipped and partial scans are disclosed. It never executes configuration, follows arbitrary imports or prints credential/configuration values.

## Conditional notices

Context usage at 85% and quota usage at 90% get attention rows. These are display thresholds, not assumed compaction thresholds. Recent observer events can show `Approval requested`, `Tool failure reported`, `Permission denied`, or a temporary compaction notice. Event notices expire after 60 seconds; subsequent matching tool-result events clear approval-request metadata.

A permission request is a historical event, not proof a dialog is still waiting. Claude can temporarily hide the statusline during permission prompts. The observer never changes permissions or interprets arbitrary command output as test results. Native `failed`/`killed` agent states are displayed directly.

There are no default sparklines, session-duration instrument, healthy badges, guessed ETAs or memory-loss scores. The old optional `contextDisplay.compactionThreshold` scaling is no longer used; percentages consistently mean the supplied actual usage.

## Diagnostics and plain output

Each mode reads its documented JSON input on stdin:

```bash
COLUMNS=100 ./context-bar.sh --plain < tests/fixtures/session.json
./context-bar.sh --subagents --plain < tests/fixtures/subagents.json
./context-bar.sh --diagnostics < tests/fixtures/session.json
```

`--plain` or `NO_COLOR` disables ANSI colors. `--ascii` replaces meter glyphs and non-ASCII text for limited fonts. Width comes from host `COLUMNS`, or native subagent `columns`; invalid values fall back to 80. The same information order reflows as width shrinks. Checklist/activity text wraps by terminal cells without dropping supported titles; long identity text may be clipped to preserve the model header. Native agents keep one host-owned row per agent, wrapping their own content when necessary. Ambiguous-width characters can vary with terminal font/settings; use ASCII when needed.

Diagnostics expose normalized metrics, observer evidence, used capability names and the local task/configuration snapshot. Task titles and file basenames can be private project information; inspect before sharing diagnostics. Context-runway and quota-exhaustion forecasts remain `null`: this release does not collect a validated rate history or know the next compaction threshold. Missing data is not rendered as a confident zero. Cache details appear only when supplied.

## Codex

Codex CLI's native `/statusline` picker selects built-in footer items; it does not execute this renderer. Configure its native model, context, account-limit and Git fields separately. This package does not modify Codex settings or add a custom footer to the Codex desktop app.

## Upgrade and rollback

The Bash entry-point path remains the same, but it now delegates to Python and must be installed with all three Python files. Existing single-file `curl` installations must switch to the full checkout. To update, run `git pull` in that checkout. To undo configuration changes, restore your settings backup or remove only the two statusline entries and the observer commands you added. Other hooks should stay intact.

## Develop

```bash
python3 -m unittest discover -s tests -v
bash -n context-bar.sh
python3 -m py_compile context_statusline.py activity.py session_snapshot.py
python3 docs/examples/render.py
```

Tests cover input validation, supplied cost accounting, missing/zero values, Unicode width and terminal controls, native JSONL, concurrent observer writes, session isolation, expiry and private storage. The fixture inputs contain no real session data. Example generation runs the same rendering functions as the executable.

Sources: [Claude statusline payload](https://code.claude.com/docs/en/statusline#available-data), [native subagent rows](https://code.claude.com/docs/en/statusline#subagent-status-lines), [hook events](https://code.claude.com/docs/en/hooks#hook-events), [task persistence](https://code.claude.com/docs/en/interactive-mode#task-list), and [Codex footer settings](https://learn.chatgpt.com/docs/developer-commands#configure-footer-items-with-statusline).

MIT licensed.

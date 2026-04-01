# Context Bar for Claude Code

A minimal statusline for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that shows real-time context window usage with a gradient progress bar.

```
── Claude Opus 4.6 │ 1000K context │ 12m3s │ $0.847
◉ CONTEXT: ⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁⛁ 37%
```

The bar gradient shifts from green -> yellow -> orange -> red as context fills up.

## What it shows

- Context usage as a gradient bar with percentage
- Active model name
- Context window size (200K / 1M)
- Session duration
- Estimated session cost (based on token counts and model pricing)

## Install

```bash
curl -o ~/.claude/context-bar.sh https://raw.githubusercontent.com/Esk3nder/context_statusline/main/context-bar.sh
chmod +x ~/.claude/context-bar.sh
```

Add the statusline to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/context-bar.sh"
  }
}
```

Restart Claude Code. The bar will appear at the bottom of the terminal.

## Responsive modes

Adapts to terminal width automatically:

| Mode | Width | Shows |
|------|-------|-------|
| nano | <35 | Model + bar + % |
| micro | 35-54 | + context size, cost |
| mini | 55-79 | + duration |
| normal | 80+ | Full display |

## Optional: Compaction threshold

If you want the bar to fill to 100% at a specific context percentage (e.g., when compaction kicks in at 62%), add `contextDisplay` to the **same** `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/context-bar.sh"
  },
  "contextDisplay": {
    "compactionThreshold": 62
  }
}
```

With this set, 62% raw usage displays as a full bar. Omit or set to `100` for raw 0-100%.

## Cost estimates

Session cost is calculated from token counts using hardcoded per-model rates. These rates reflect [Anthropic's pricing](https://docs.anthropic.com/en/about-claude/pricing) as of April 2026. If Anthropic changes their pricing, the estimates will be inaccurate until the rates in `context-bar.sh` are updated. PRs to update pricing are welcome.

## Requirements

- Bash 4+
- `jq` (JSON parsing)
- `awk` (cost calculation — available on all UNIX systems)
- A terminal with truecolor support (most modern terminals)

On macOS, install `jq` with `brew install jq`. On Debian/Ubuntu: `sudo apt install jq`.

## License

MIT

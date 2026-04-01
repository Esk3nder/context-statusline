# Context Statusline for Claude Code

A minimal statusline for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that shows real-time context window usage with a gradient progress bar.

<p align="center">
  <img width="351" height="114" alt="Context statusline screenshot" src="https://github.com/user-attachments/assets/8efdc2dd-d2ec-4ff0-90e3-42a495cc08cd" />
</p>

```
── Claude Opus 4.6 (1M context) │ 12m3s │ $0.847
◉ CONTEXT: ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁ ⛁  37%
```

The bar gradient shifts from green → yellow → orange → red as context fills up.

## Install

Requires `jq` — install with `brew install jq` (macOS) or `sudo apt install jq` (Debian/Ubuntu).

```bash
curl -o ~/.claude/context-bar.sh \
  https://raw.githubusercontent.com/Esk3nder/context-statusline/main/context-bar.sh
chmod +x ~/.claude/context-bar.sh
```

Add to `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/context-bar.sh"
  }
}
```

Restart Claude Code.

## Features

- **Context bar** — gradient progress bar showing context window usage
- **Model name** — active model displayed in the header
- **Session duration** — how long the current session has been running
- **Session cost** — estimated cost based on token counts and [Anthropic pricing](https://docs.anthropic.com/en/about-claude/pricing)
- **Responsive** — adapts to terminal width (nano / micro / mini / normal)

## Compaction threshold (optional)

If you want the bar to reach 100% at a specific context percentage (e.g., when compaction kicks in at 62%):

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

Omit or set to `100` for raw 0–100% display.

## License

MIT

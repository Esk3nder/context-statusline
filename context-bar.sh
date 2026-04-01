#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# Claude Code Context Bar
# ═══════════════════════════════════════════════════════════════════════════════
#
# Minimal statusline showing real-time context window usage with gradient bar.
# Responsive: adapts to terminal width (nano/micro/mini/normal).
#
# Install:
#   1. Copy this file to ~/.claude/context-bar.sh && chmod +x
#   2. Add to ~/.claude/settings.json:
#      { "statusLine": { "type": "command", "command": "~/.claude/context-bar.sh" } }
#
# Optional: Set compaction threshold in settings.json to scale the bar:
#   { "contextDisplay": { "compactionThreshold": 62 } }
#   When set, 62% raw usage displays as 100% (bar fills to compaction point).
#   Set to 100 or omit for raw 0-100% display.
#
# ═══════════════════════════════════════════════════════════════════════════════

set -o pipefail

# ─────────────────────────────────────────────────────────────────────────────
# DEPENDENCY CHECK
# ─────────────────────────────────────────────────────────────────────────────

if ! command -v jq >/dev/null 2>&1; then
    echo "context-bar: jq is required but not installed" >&2
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# PARSE INPUT (Claude Code pipes JSON on stdin)
# ─────────────────────────────────────────────────────────────────────────────

input=$(cat)

SETTINGS_FILE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"

IFS=$'\t' read -r model_name context_max context_pct total_input total_output duration_ms \
  < <(echo "$input" | jq -r '[
    (.model.display_name // "unknown"),
    (.context_window.context_window_size // 200000 | tostring),
    (.context_window.used_percentage // 0 | tostring),
    (.context_window.total_input_tokens // 0 | tostring),
    (.context_window.total_output_tokens // 0 | tostring),
    (.cost.total_duration_ms // 0 | tostring)
  ] | join("\t")' 2>/dev/null)

context_pct=${context_pct:-0}
context_max=${context_max:-200000}
total_input=${total_input:-0}
total_output=${total_output:-0}
model_name=${model_name:-unknown}

# ─────────────────────────────────────────────────────────────────────────────
# SESSION COST (real-time from token counts)
# ─────────────────────────────────────────────────────────────────────────────

session_cost=""
if [ "$total_input" -gt 0 ] || [ "$total_output" -gt 0 ]; then
    # Pricing per 1M tokens — update if Anthropic changes rates
    # https://docs.anthropic.com/en/about-claude/pricing
    model_lower=$(echo "$model_name" | tr '[:upper:]' '[:lower:]')
    case "$model_lower" in
        *opus*4*)   in_rate="5.00";  out_rate="25.00" ;;
        *sonnet*4*) in_rate="3.00";  out_rate="15.00" ;;
        *haiku*4*)  in_rate="1.00";  out_rate="5.00"  ;;
        *)          in_rate="3.00";  out_rate="15.00" ;;
    esac
    session_cost=$(awk "BEGIN {
        cost = ($total_input * $in_rate + $total_output * $out_rate) / 1000000
        if (cost < 0.01) printf \"\$%.4f\", cost
        else if (cost < 1.00) printf \"\$%.3f\", cost
        else printf \"\$%.2f\", cost
    }")
fi

# ─────────────────────────────────────────────────────────────────────────────
# DURATION
# ─────────────────────────────────────────────────────────────────────────────

duration_sec=$((${duration_ms:-0} / 1000))
if   [ "$duration_sec" -ge 3600 ]; then duration="$((duration_sec / 3600))h$((duration_sec % 3600 / 60))m"
elif [ "$duration_sec" -ge 60 ];   then duration="$((duration_sec / 60))m$((duration_sec % 60))s"
else duration="${duration_sec}s"
fi

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL WIDTH
# ─────────────────────────────────────────────────────────────────────────────

detect_width() {
    local w=""
    w=$(stty size </dev/tty 2>/dev/null | awk '{print $2}')
    [ -z "$w" ] || [ "$w" = "0" ] && w=$(tput cols 2>/dev/null)
    [ -z "$w" ] || [ "$w" = "0" ] && w="${COLUMNS:-80}"
    echo "$w"
}

term_width=$(detect_width)

if   [ "$term_width" -lt 35 ]; then MODE="nano"
elif [ "$term_width" -lt 55 ]; then MODE="micro"
elif [ "$term_width" -lt 80 ]; then MODE="mini"
else MODE="normal"
fi

# ─────────────────────────────────────────────────────────────────────────────
# COLORS
# ─────────────────────────────────────────────────────────────────────────────

RESET='\033[0m'
SLATE_300='\033[38;2;203;213;225m'
SLATE_400='\033[38;2;148;163;184m'
SLATE_500='\033[38;2;100;116;139m'
SLATE_600='\033[38;2;71;85;105m'
EMERALD='\033[38;2;74;222;128m'
ROSE='\033[38;2;251;113;133m'

# Context theme (indigo)
CTX_PRIMARY='\033[38;2;129;140;248m'
CTX_SECONDARY='\033[38;2;165;180;252m'
CTX_BUCKET_EMPTY='\033[38;2;75;82;95m'

# ─────────────────────────────────────────────────────────────────────────────
# GRADIENT BAR
# ─────────────────────────────────────────────────────────────────────────────

# Green(74,222,128) → Yellow(250,204,21) → Orange(251,146,60) → Red(239,68,68)
get_bucket_color() {
    local pos=$1 max=$2
    local pct=$((pos * 100 / max))
    local r g b

    if [ "$pct" -le 33 ]; then
        r=$((74 + (250 - 74) * pct / 33))
        g=$((222 + (204 - 222) * pct / 33))
        b=$((128 + (21 - 128) * pct / 33))
    elif [ "$pct" -le 66 ]; then
        local t=$((pct - 33))
        r=$((250 + (251 - 250) * t / 33))
        g=$((204 + (146 - 204) * t / 33))
        b=$((21 + (60 - 21) * t / 33))
    else
        local t=$((pct - 66))
        r=$((251 + (239 - 251) * t / 34))
        g=$((146 + (68 - 146) * t / 34))
        b=$((60 + (68 - 60) * t / 34))
    fi
    printf '\033[38;2;%d;%d;%dm' "$r" "$g" "$b"
}

render_bar() {
    local width=$1 pct=$2
    local filled=$((pct * width / 100))
    [ "$filled" -lt 0 ] && filled=0

    local output=""
    for ((i = 1; i <= width; i++)); do
        if [ "$i" -le "$filled" ]; then
            local color=$(get_bucket_color $i $width)
            output="${output}${color}⛁${RESET}"
        else
            output="${output}${CTX_BUCKET_EMPTY}⛁${RESET}"
        fi
        [ "$width" -gt 8 ] && output="${output} "
    done
    output="${output% }"
    echo "$output"
}

calc_bar_width() {
    local mode=$1
    case "$mode" in
        nano)   echo 5 ;;
        micro)  echo 6 ;;
        mini)   echo 8 ;;
        normal) echo 16 ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────────────
# CONTEXT SCALING (compaction threshold)
# ─────────────────────────────────────────────────────────────────────────────

COMPACTION_THRESHOLD=100
[ -f "$SETTINGS_FILE" ] && COMPACTION_THRESHOLD=$(jq -r '.contextDisplay.compactionThreshold // 100' "$SETTINGS_FILE" 2>/dev/null)
COMPACTION_THRESHOLD="${COMPACTION_THRESHOLD:-100}"

raw_pct="${context_pct%%.*}"
[ -z "$raw_pct" ] && raw_pct=0

if [ "$COMPACTION_THRESHOLD" -lt 100 ] && [ "$COMPACTION_THRESHOLD" -gt 0 ]; then
    display_pct=$((raw_pct * 100 / COMPACTION_THRESHOLD))
    [ "$display_pct" -gt 100 ] && display_pct=100
else
    display_pct="$raw_pct"
fi

# Percentage color
if   [ "$display_pct" -ge 80 ]; then pct_color="$ROSE"
elif [ "$display_pct" -ge 60 ]; then pct_color='\033[38;2;251;146;60m'
elif [ "$display_pct" -ge 40 ]; then pct_color='\033[38;2;251;191;36m'
else pct_color="$EMERALD"
fi

# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────

max_k=$((context_max / 1000))
bar_width=$(calc_bar_width "$MODE")
bar=$(render_bar $bar_width $display_pct)

# Header
case "$MODE" in
    nano)
        printf "${SLATE_600}──${RESET} ${SLATE_400}${model_name}${RESET}\n"
        ;;
    micro)
        printf "${SLATE_600}──${RESET} ${SLATE_400}${model_name}${RESET}"
        [ -n "$session_cost" ] && printf " ${SLATE_600}│${RESET} ${SLATE_300}${session_cost}${RESET}"
        printf "\n"
        ;;
    mini)
        printf "${SLATE_600}──${RESET} ${SLATE_400}${model_name}${RESET} ${SLATE_600}│${RESET} ${SLATE_500}${duration}${RESET}"
        [ -n "$session_cost" ] && printf " ${SLATE_600}│${RESET} ${SLATE_300}${session_cost}${RESET}"
        printf "\n"
        ;;
    normal)
        printf "${SLATE_600}──${RESET} ${SLATE_400}${model_name}${RESET} ${SLATE_600}│${RESET} ${SLATE_500}${duration}${RESET}"
        [ -n "$session_cost" ] && printf " ${SLATE_600}│${RESET} ${SLATE_300}${session_cost}${RESET}"
        printf "\n"
        ;;
esac

# Context bar
case "$MODE" in
    nano|micro)
        printf "${CTX_PRIMARY}◉${RESET} ${bar}  ${pct_color}${raw_pct}%%${RESET}\n"
        ;;
    mini|normal)
        printf "${CTX_PRIMARY}◉${RESET} ${CTX_SECONDARY}CONTEXT:${RESET} ${bar}  ${pct_color}${raw_pct}%%${RESET}\n"
        ;;
esac

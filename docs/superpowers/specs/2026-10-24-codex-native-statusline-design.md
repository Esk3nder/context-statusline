# Shared native statusline for Claude and Codex

User approved a self-owned, minimal Codex patch on October 24, 2026. No upstream acceptance, new terminal, companion pane or changes to model behavior are dependencies. Use the approved wide neutral renderer for both hosts. Preserve stock Codex and existing managed settings; install an explicitly named launcher alongside stock. Work inline in isolated worktrees, carrying a distributable patch against upstream rust-v0.164.0.

## Architecture

The Codex TUI gains one private module for a bounded external-renderer panel, enabled only by CODEX_STATUSLINE_COMMAND containing a JSON argv array. No shell expansion and no project-supplied command configuration. It receives a versioned, allowlisted stdin JSON snapshot from native widget/event state; never raw prompts, commands, tool inputs/results, transcript or credentials. Existing native status/footer behavior remains the fallback on disabled/broken renderers. Keep dialogs/composer usable and clip the custom panel first in short terminals. One worker maximum, throttled to 500ms, 500ms render timeout, 64 KiB stdout limit, 64-row safety cap; ANSI becomes ratatui cells, never direct terminal escape writes. Disclose clipping/unsupported/missing data instead of guessing.

A Codex adapter in this package maps native context, model/effort, quotas, observed tool metadata, current plan and supplied agent states into the existing renderer. Codex elapsed time is explicitly since attachment; costs appear only when supplied, with scope labeled. Do not read Claude task/config/cache state from the Codex adapter. Observed child states are exact-ID snapshots; child tools appear only when received, never inferred. Native AGENTS/config counts must reflect known discovery; unavailable counts are omitted, not zero. Config discovery/usage remain different concepts.

## Distribution and maintenance

Keep the renderer outside Codex. Carry the small source patch and pinned base metadata in this repo, with an application/build verification script and CI targets for macOS/Linux/Windows. A Python installer installs a versioned bundle and codex-statusline launcher alongside stock, supports paths containing spaces, stages/verifies before activation, and supports rollback/uninstall without changing credentials or global agent config. Build the local Mac binary and demonstrate the real embedded panel. Remote platform binaries are only claimed after corresponding builds pass; never publish release assets without completing review/validation.

## Verification

Failing tests first for adapter privacy/host separation, sparse/invalid data, quotas/context/plan/agent mappings, subprocess timeout/output/error isolation, safe ANSI rendering, width/height/composer layout and installer/rollback. Keep all existing Claude tests and golden examples green. Compile and run focused Rust TUI tests including a rendered snapshot. Verify patch applies cleanly to the exact pinned base; archive the independent final review and address Important findings once with regressions. User approval covers implementation and draft PR updates, not a merge or changing their default codex command.

Sources already checked: official Codex footer configuration and app-server protocol; installed 0.164.0 generated schemas; upstream rust-v0.164.0 source. The extension is ours, not an officially supported Codex setting.

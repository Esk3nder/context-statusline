# Codex Native Statusline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the shared wide statusline embedded in a separately installed Codex build.
**Architecture:** A minimal optional TUI subprocess bridge supplies allowlisted native metadata to the shared Python renderer; installer keeps stock Codex untouched.
**Tech Stack:** Rust/Tokio/ratatui and Python standard library.
**Spec:** docs/superpowers/specs/2026-10-24-codex-native-statusline-design.md

## Global Constraints

No upstream acceptance, new terminal, companion pane or changes to model behavior are dependencies. Preserve stock Codex and existing managed settings. No shell expansion, raw transcripts, prompts, commands, results or credentials in renderer input. 500ms throttle/timeout, 64 KiB stdout, 64 rows; preserve native footer fallback and prioritize composer/dialogs. Codex adapter must never use Claude state. Label missing/scope-limited data honestly. Local Mac binary plus reproducible pinned patch; other binary platforms require their own verification.

## Review Focus

- Renderer lifetime and stale output after thread switching/resizing; correlate dimensions and per-widget worker identity.
- Hung/oversized/nonzero renderer cannot block input or leak children; regression in Task 2.
- Host separation and privacy even with malformed metadata; regressions in Task 1.
- Tiny terminals and active dialogs preserve input, with UI snapshot in Task 2.
- Installer rollback/paths with spaces and tampered bundles preserve stock config/binary; regressions in Task 3.

### Task 1: Shared Codex data adapter

**Files:** codex_statusline.py, context_statusline.py, tests/test_codex.py, tests/fixtures/codex.json.
**Interfaces:** main(data,width,color,now) maps versioned host JSON into render_main + native agent rows. Uses existing renderer functions; does not call Claude snapshots/cache.
- [ ] Add tests for native token/context and arbitrary quota durations, plan states, bounded labels, sparse data, no secrets/raw data/Claude cache and existing neutral design.
- [ ] Run unittest targeted tests RED, implement adapter and small host-label/cost-scope support, rerun full suite GREEN; commit.

### Task 2: Minimal Codex native patch

**Files:** private tui/src/context_statusline.rs + tests; small hooks in lib.rs, chatwidget.rs, constructor.rs, protocol.rs, status_surfaces.rs and rendering.rs. Save patch/base metadata under codex/ in this package.
**Interfaces:** Panel::from_env(FrameRequester), Panel::observe(&ServerNotification), Panel::update(Value), Renderable panel. JSON argv process returns ANSI text; native metadata never serialized wholesale.
- [ ] Tests RED for process success/nonzero/timeout/oversize and output sanitization, snapshot/layout.
- [ ] Implement bounded one-worker renderer, native snapshot and event metadata; host wiring with stock fallback and input priority.
- [ ] Focused Rust tests and build; real TUI smoke test; regenerate distributable patch; commit.

### Task 3: Installation and reproducible distribution

**Files:** install_codex.py, tests/test_install_codex.py, codex/build.py, codex/upstream.json, workflow and README.
**Interfaces:** installer takes a verified local bundle/binary, creates versioned owned install and named launcher, no stock overwrite; build script checks pinned base/patch then produces platform bundle/checksums.
- [ ] Installer regression tests RED, implement staging/activation/rollback; full suite GREEN.
- [ ] Build local binary/bundle, install alongside stock, smoke test real launcher and renderer. Add cross-platform build workflow and correct scope/maintenance docs.
- [ ] Independent final review; one regression fix pass; local tests/lint/patch checks and latest hosted CI. Commit/push draft PR; preserve live settings and stock command.

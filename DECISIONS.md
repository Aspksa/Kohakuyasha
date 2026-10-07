# Decisions

## D-001 — Repository is the single source of truth
**Date:** 2026-10-07  
**Status:** Active

All durable project decisions, project state, task state, version history, and error history must be stored in this repository. Chat must not be the only location of important project information.

## D-002 — Minimal-chat operating mode
**Date:** 2026-10-07  
**Status:** Active

Development communication should be compact: plan, material blockers/errors, and final result. Routine low-level operations are not narrated.

## D-003 — Portable Windows-first architecture
**Date:** 2026-10-07  
**Status:** Active

The project must run from an arbitrary folder or removable drive. Paths are resolved relative to the repository root. Runtime, data, logs and configuration remain local to the project unless Windows autostart explicitly requires a small startup entry.

## D-004 — Localhost-only web control plane
**Date:** 2026-10-07  
**Status:** Superseded by D-007

The initial v0.1.0 model relied primarily on localhost binding and a custom action marker. v0.1.1 hardens this model.

## D-005 — SQLite is the initial state database
**Date:** 2026-10-07  
**Status:** Active

SQLite with WAL is the initial persistent database. Schema upgrades create only health-checked backups. Recovery quarantines the damaged database and restores only a backup that passes SQLite quick_check/integrity validation. Backup retention is bounded.

## D-006 — BAT is a thin bootstrap entrypoint
**Date:** 2026-10-07  
**Status:** Active

`Kohakuyasha.bat` is only the user-facing launcher. Complex setup logic lives in PowerShell and application logic lives in Python.

## D-007 — Browser security is explicit, not implied by localhost
**Date:** 2026-10-07  
**Status:** Active

All HTTP requests require a local Host. API requests additionally require a per-process HttpOnly SameSite=Strict session cookie. Browser mutations require exact same-origin Origin plus an action marker. WebSocket connections require local Host, exact same-origin Origin and the same session cookie. Security response headers deny framing and restrict content/connect sources.

## D-008 — Production runtime and developer tests are separate
**Date:** 2026-10-07  
**Status:** Active

Normal startup installs only runtime dependencies and never runs pytest. Test tooling lives in `requirements-dev.lock` and a separate `.runtime/dev-venv`. The web Test Center runs application diagnostics, not the developer test suite.

## D-009 — Runtime versions are pinned and interpreter-bound
**Date:** 2026-10-07  
**Status:** Active

Portable Python is pinned by `PYTHON_VERSION`. Python package versions are exactly pinned in lock files. Dependency installation state includes the interpreter executable SHA-256, Python version, environment kind and requirements hash, so replacing an interpreter invalidates dependency state.

## D-010 — Installation identity is generated locally
**Date:** 2026-10-07  
**Status:** Active

`.kohakuyasha-id` is not committed. It is generated on first local use and is ignored by Git. Windows autostart searches attached drives for the exact instance ID, allowing drive-letter changes without treating every repository clone as the same installation.
## D-011 — Windows CI is a required validation surface
**Date:** 2026-10-07  
**Status:** Active

Every change targeting the Windows runtime must pass the GitHub Actions Windows job before merge. The CI also runs on Linux to catch portability regressions. Python is selected from `PYTHON_VERSION`; Windows PowerShell scripts are parsed by Windows PowerShell 5.1. Physical tray/removable-drive/autostart behavior still requires a real Windows integration check.

## D-012 — AI API key is stored locally, never returned
**Date:** 2026-10-07
**Status:** Active

The provider API key is written only to `data/secrets.json` (git-ignored, chmod 600 where supported). The HTTP API exposes only `has_key` and the last four characters; the key is never logged or echoed in provider error text. Non-secret AI and avatar settings live in the SQLite `app_settings` table. Windows DPAPI encryption is a possible later hardening.

## D-013 — Avatar is a global floating widget
**Date:** 2026-10-07
**Status:** Active

The avatar is shown on every page/module, draggable, with persisted per-browser position. Left click opens chat, right click (or touch long-press) opens the personal cabinet. Default appearance is face-only with soft edges (no circle); crop, shape, size, ring, glow and status dot are user settings. Chat text is untrusted and rendered only via DOM nodes (no innerHTML) under the strict CSP.

## D-014 — Uploaded images are re-encoded server-side and served from a whitelist
**Date:** 2026-10-07
**Status:** Active

Avatar faces and backgrounds are uploaded as base64 JSON (no multipart dependency), decoded with Pillow, re-encoded (metadata stripped, size limited) and stored under `data/media/` with content-derived names. Only names matching a strict pattern are served from `/media/`. Request bodies over 9 MB are rejected.

## D-015 — Memory is retrieval, not training
**Date:** 2026-10-07
**Status:** Active

Imported dialogs, notes and (optionally) live chat are stored in SQLite and searched with FTS5; the best fragments are added to the system prompt. This works with every provider, needs no GPU and keeps data local. Fine-tuning and embeddings are future options.

## D-016 — Navigation is Overview and Settings only
**Date:** 2026-10-07
**Status:** Active

Observation, Tests and Journal pages were removed from the UI at the owner's request. Diagnostics and event APIs remain for the tray and export. Appearance, clock and startup options live in Settings; AI, avatar and memory live in the personal cabinet.

## D-017 — Visual identity: soft kitsune style
**Date:** 2026-10-07
**Status:** Active

The interface uses a soft fox-spirit look: serif display headings, gradient-edged rounded cards, a faint seigaiha wave pattern, glowing tail-shaped light blobs and slow sakura petals. All components share radius/shadow/button tokens in `app.css`. Decorations are optional (Settings: pattern, petals, animations) and never carry information. Stopping a reply is cooperative: the provider call cannot be aborted, so the answer is discarded server-side via `/api/chat/cancel`.

## D-018 — Cloud.ru is the only AI provider
**Date:** 2026-10-07
**Status:** Active

At the owner's request the Anthropic and OpenAI-compatible providers were removed. The assistant talks only to Cloud.ru Evolution Foundation Models (OpenAI-compatible chat completions) with DeepSeek V4 Flash (default) and V4 Pro offered as model cards plus a custom model id. Legacy stored provider values fall back to Cloud.ru. Without a key the assistant answers with a notice explaining how to connect.

## D-019 — Overview uses fixed component sizes
**Date:** 2026-10-07
**Status:** Active

Clock, calendar cells and the side column use fixed pixel sizes and the page content is capped at 1160px, so resizing or maximising the window never rescales them. Responsive changes happen only at explicit breakpoints and container-query widths.

## D-020 — Assistant memory is distilled, local and user-editable
**Date:** 2026-10-07
**Status:** Active

Beyond retrieval over imported dialogs (D-015) the assistant keeps (a) a facts table distilled from conversations by a short, low-cost provider request every N user messages or immediately for «Запомни …», (b) a rolling summary of older messages, and (c) the current date/time and upcoming calendar notes. Facts are ranked by importance, pinning, word overlap and recency, near-duplicates are merged, and every fact can be edited, pinned or deleted in the cabinet. Extraction runs after the reply in a background thread and never blocks or fails a chat turn; provider errors are logged as events. Nothing leaves the machine except the prompts sent to Cloud.ru.

## D-021 — Self-update from GitHub with backups
**Date:** 2026-10-07
**Status:** Active

The project updates itself from the configured GitHub repository (default Aspksa/Kohakuyasha, branch main). The updater reads the remote `VERSION`, shows newer `CHANGELOG.jsonl` entries, downloads the branch zipball over HTTPS, validates it (required files, no path traversal, size limits), and replaces only files outside the protected paths (`data/`, `logs/`, `.runtime/`, `.git/`, `.kohakuyasha-id`; `tests/` and `.github/` are not installed). Every replaced or removed file is copied to `.runtime/backups/<from>-<time>` first (last 3 kept) and a failed apply is undone; a manifest lets later updates delete files a release dropped. Nothing is installed without a user click; auto-check only shows a badge. A private repository needs a fine-grained read-only token stored in `data/secrets.json` (never returned, never forwarded to another host on redirect). A new version takes effect after a full relaunch (`Kohakuyasha.bat`, started by a short detached PowerShell on Windows).

## D-022 — No backdrop blur; calendar and clock removed
**Date:** 2026-10-07
**Status:** Active

`backdrop-filter` is banned in the UI: measurements showed it dominated frame time. Panels use opaque or high-opacity backgrounds; background glows are radial gradients. The clock and calendar (and the assistant's calendar context) were removed at the owner's request; the overview shows status, assistant and update cards.

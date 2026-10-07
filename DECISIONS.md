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
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
**Status:** Active

The web UI binds to 127.0.0.1 by default. Control actions require a custom request header so ordinary cross-origin HTML forms cannot trigger them. No LAN exposure is enabled by default.

## D-005 — SQLite is the initial state database
**Date:** 2026-10-07  
**Status:** Active

SQLite with WAL is the initial persistent database. Schema upgrades must create a backup before migration; corruption recovery preserves the damaged file and attempts restoration from the newest backup.

## D-006 — BAT is a thin bootstrap entrypoint
**Date:** 2026-10-07  
**Status:** Active

`Kohakuyasha.bat` is only the user-facing launcher. Complex setup logic lives in PowerShell and application logic lives in Python, avoiding an unmaintainable BAT implementation.

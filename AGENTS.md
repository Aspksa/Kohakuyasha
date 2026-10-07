# AGENTS.md

## Project
Kohakuyasha — repository `Aspksa/Kohakuyasha`. This repository is the single source of truth.

## TURBO operating mode
Work continuously with minimum GitHub/API calls. Use: `SNAPSHOT → ANALYZE → PATCH → TEST → COMMIT → PUSH → CI → NEXT`. After a green safe stage, continue to the next logical stage without asking for routine confirmation.

## Snapshot discipline
At a new session, external repository change, unknown state, or contradiction, check only: branch, HEAD, status/diff, VERSION, PROJECT_STATE, related files and critical CI. Do not repeatedly audit the whole repository between sequential stages.

## Git discipline
- Prefer `feature/fix branch → targeted tests → PR → required checks → main`.
- Never force-push main or bypass branch protection.
- One logical stage should use one commit or a compact tightly-related series.
- Batch related reads/writes; do not reopen unchanged files.

## Defect discipline
Existing defect first: `failure/bug → reproduce → root cause → minimal fix → regression test → continue`. Do not build new functionality on a known broken foundation.

## Testing ladder
Use the smallest sufficient level first: targeted → module → integration → smoke → CI. Windows is mandatory for Windows-facing functionality. Do not call a Windows stage complete solely from Linux validation.

## Safety
Without explicit permission do not perform destructive history rewrites, force pushes, main deletion, bulk irreversible migrations, user-data deletion, secret publication, or security disabling. Never commit `.env`, API keys, tokens, runtime data, or generated installation identity.

## Architecture
Prefer modular components with clear interfaces, isolated settings, permissions/security boundaries, health/status, versioning and migrations where needed. Do not duplicate an existing service/API/configuration/registry when it can be safely extended.

## Version/state discipline
Synchronize VERSION, README, PROJECT_STATE, changelog and related release metadata for a completed version. PROJECT_STATE should record `current_version`, `completed_stage`, `current_branch`, validated `head_commit`, tests, CI, known issues and exactly one executable `next_action`.

## Required state updates
For each completed stage update PROJECT_STATE, TASKS when status changes, append CHANGELOG, append material errors/fixes to ERRORS, update VERSION when applicable, and record durable architecture/product decisions in DECISIONS. JSONL history is append-only.

## Chat output
Keep chat minimal. Intermediate status only for a serious defect, plan change, blocker, major stage completion, or required user action. Preferred status: `Этап / Найдено / Исправлено / Проверка / Дальше`. Final result should be compact and evidence-based.

# AGENTS.md

## Core rule
This repository is the single source of truth. Never keep a durable project decision only in chat.

## Start of every work unit
Read, in this order:
1. VERSION
2. PROJECT_STATE.json
3. TASKS.json
4. DECISIONS.md when relevant
5. CHANGELOG.jsonl and ERRORS.jsonl only as needed

Do not reconstruct state from chat when repository state is available.

## Working mode
- Keep chat output minimal: short plan, material blocker/error, final result.
- Batch independent read operations.
- Make coherent changes in as few write operations/commits as practical.
- Do not repeat already-known context.
- Run relevant validation/tests before marking work complete.
- After successful validation, commit/push immediately unless technically blocked.
- If main is protected, use a branch and PR instead of bypassing protection.

## Required state updates
For each completed work unit:
- update PROJECT_STATE.json
- update TASKS.json when task state changes
- append a record to CHANGELOG.jsonl
- append material errors and their resolution to ERRORS.jsonl
- update VERSION when the release/version changes
- record durable architectural/product decisions in DECISIONS.md

## History rules
- CHANGELOG.jsonl and ERRORS.jsonl are append-only.
- Never erase historical failures; mark later records as resolved/fixed.
- Every JSONL line must be valid standalone JSON.
- Prefer stable IDs for tasks, errors, and decisions.

## Chat result format
Plan: <task> -> <validation> -> <commit/push>

Result: <status> | <tests/checks> | <commit/PR> | next: <next_action>

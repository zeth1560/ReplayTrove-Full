# Unified Configuration Architecture

## Objectives

- Single source of truth for **operator-editable settings** (paths, ports, feature flags, appliance tuning)
- Typed schema, defaults, validation, and migrations in `packages/config`
- Control Center UI for editing, validating, and exporting `config/settings.json`
- Preserve **env overrides** and **compatibility bridges** (e.g. legacy command-bus paths) during migration

## Monorepo layout

- `config/settings.json` — central settings on the appliance
- `config/settings.secrets.template.json` — documentation / template only (no real secrets committed)
- `packages/config` — schema, defaults, validation, migrations
- `apps/control-center` — operator GUI
- `tools/validate-config.ts` — CLI validation report

## Data model boundaries

- **Primary settings:** central JSON (`config/settings.json`), edited via Control Center or hand-merge with validation
- **Highly sensitive tokens:** e.g. `REPLAY_CANONICAL_TOKEN` — env (or secret store), not required to live in JSON
- **OBS websocket password:** present in schema as `scoreboard.obsWebsocketPassword` for appliance simplicity; treat **`config/settings.json` permissions** as security-sensitive if populated
- **Derived/runtime state:** `state/`, command pending/processed files, status JSON — not the unified schema’s role

## Compatibility strategy

- Worker, scoreboard, and canonical PowerShell resolve **unified-first**, then env, then code/script defaults, with logging when fallbacks apply.
- Legacy behaviors (e.g. second command-bus pending scan) remain until explicitly retired.

## Versioning and migrations

- `schemaVersion` in the config document
- Migration functions by version; validation runs after migration

## Validation coverage

- Schema type/range checks, path existence where configured, URL/port sanity, basic cross-field checks

## Status after Phase 1

- Adapters are integrated into worker/scoreboard startup and canonical replay script resolution paths.
- Control Center read/write is wired to the same `config/settings.json`.
- Remaining incremental work: broader operator docs, optional stricter enforcement modes, and future pruning of redundant env-only paths once usage is fully observed.

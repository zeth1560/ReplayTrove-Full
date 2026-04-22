# Unified Configuration Architecture (Phase 1)

## Objectives

- Single source of truth for **non-secret editable settings**
- Keep **secrets** out of editable config (env/OS secret store only)
- Add typed schema, defaults, validation, and migrations
- Provide Control Center UI for editing settings centrally
- Preserve compatibility with existing env-based apps during migration

## Proposed Monorepo Structure

- `config/settings.json` - editable central settings
- `config/settings.secrets.template.json` - documentation only (no real secrets)
- `packages/config` - schema, defaults, validation, migrations, adapters metadata
- `apps/control-center` - operator GUI for editing/validating/exporting config
- `tools/validate-config.ts` - CLI validation report

## Data Model Boundaries

- **Editable operator settings**: central JSON (`config/settings.json`)
- **Secrets**: env / machine secret store only
- **Derived/runtime state**: state/commands/status files (unchanged)

## Compatibility Strategy

- Existing env loaders remain source of runtime behavior for now.
- New config package provides migration-ready schema and validation.
- Next phase: app-by-app adapters map central settings -> current app runtime fields.

## Versioning and Migrations

- `schemaVersion` in config document
- Explicit migration functions by version
- Validation always runs post-migration

## Validation Coverage (Phase 1)

- Schema-level type/range checks
- Path existence checks (where configured)
- URL + port sanity checks
- Cross-setting conflicts (basic)

## Remaining Work After Phase 1

- Integrate adapters into worker/scoreboard/launcher startup paths
- Replace hardcoded script defaults with central settings lookups
- Wire Control Center save/load to live operator workflow
- Add section-level reset + import/export UI actions

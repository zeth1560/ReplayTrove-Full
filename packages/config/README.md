# @replaytrove/config

Shared typed configuration package for ReplayTrove monorepo.

## Responsibilities

- Single source of truth schema (`schema.ts`)
- Defaults (`defaults.ts`)
- Version migrations (`migrations.ts`)
- Validation report (`validate.ts`)
- Load/save helpers (`io.ts`)

## Current status

Phase 1 scaffold complete. Existing runtime apps still read env/config as before.
Future phases will integrate per-app adapters to map central settings into app runtime config.

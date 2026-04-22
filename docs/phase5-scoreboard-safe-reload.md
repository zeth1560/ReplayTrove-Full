# Phase 5 Implementation Note: Scoreboard Safe Live Reload

This note documents the implemented, intentionally narrow Phase 5 live-reload behavior.

## Approved allowlist (implemented)

Only these settings are live-reloadable:

- `scoreboard.obsStatusPollIntervalMs`
- `scoreboard.encoderStatusPollMs`

## Explicit non-goals (still excluded)

- No worker live reload
- No launcher live reload
- No `scoreboard.replayFileMaxAgeSeconds` live reload
- No paths, executable settings, ports, startup toggles, or process-launch wiring
- No automatic save-triggered apply
- No config file watcher
- No global hot-reload framework

## Command contract

- Command action: `reload_scoreboard_safe_settings`
- Transport: existing scoreboard command bus (`commands/scoreboard/pending`)
- Trigger: explicit operator action from Control Center

## Command flow

1. Operator saves config (normal save flow, separate from reload).
2. Operator clicks **Apply safe live settings to scoreboard**.
3. Control Center API enqueues command JSON.
4. Running scoreboard command loop consumes command.
5. Scoreboard reads unified config from disk.
6. Scoreboard validates allowlisted keys.
7. Scoreboard either:
   - applies both values (all-or-nothing), or
   - rejects and preserves last known good runtime snapshot.

## Validation and apply behavior

- Both values must be integers.
- Conservative bounds: `100..60000` ms.
- If either value fails validation, neither is applied.
- Runtime fallback is preserved on parse errors, validation failures, and unexpected exceptions.

## Last reload outcome status artifact

Scoreboard writes:

- `C:\ReplayTrove\scoreboard\reload_safe_settings_status.json`

Shape:

```json
{
  "timestamp": "2026-04-22T00:00:00.000Z",
  "correlation_id": "....",
  "status": "applied|rejected",
  "applied_fields": [
    "scoreboard.obsStatusPollIntervalMs",
    "scoreboard.encoderStatusPollMs"
  ],
  "schema_version": 1,
  "rejection_reason": "..." 
}
```

`rejection_reason` is present for rejected outcomes.

## Logging lifecycle

Reload lifecycle logs (structured text fields):

- `reload_attempted`
- `reload_applied`
- `reload_rejected`
- `reload_fallback_preserved`

## Future expansion rules

- Keep save and reload separate for predictability and low blast radius.
- Prefer explicit operator-triggered action over automatic reload.
- Keep worker/launcher excluded until a dedicated, bounded design is approved.
- Keep `replayFileMaxAgeSeconds` deferred until first-wave stability and operator validation are complete.

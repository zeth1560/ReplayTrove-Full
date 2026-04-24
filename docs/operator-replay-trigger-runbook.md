# Replay trigger runbook (operators & installers)

Practical guide: **what to wire for instant replay** on a ReplayTrove appliance. For architecture details, see other docs in `docs/`.

**Repeatable default:** checked-in **golden profile** (wrappers + installer notes): `operator-profiles/golden-appliance/README.md`.

---

## Use this (canonical)

| What | When |
|------|------|
| **`scripts/save_replay_and_trigger.ps1`** | **Default choice** for a replay button: saves the OBS replay buffer, calls the worker over **HTTP `/replay`**, waits for success, then tells the scoreboard to show replay (`replay_on`). One script = one coherent pipeline. |

**HTTP port:** Whatever is in **`config/settings.json`** → `worker.httpReplayTriggerPort` (Control Center shows this under replay readiness). The **stock default is `18765`** (`packages/config` defaults). Every shortcut, Companion action, or firewall rule must use **that** value unless you intentionally changed it everywhere.

**Host:** Usually `127.0.0.1`, from the same config key `worker.httpReplayTriggerHost`.

### Companion / Stream Deck (recommended: no script lockout)

If **Companion** (or another tool) already debounces or rate-limits the button, **call the canonical script directly**—do **not** use `replay_start_gate.ps1` or `replay_gate_check.ps1`. One action is enough.

**Example (hidden window):**

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\ReplayTrove\scripts\save_replay_and_trigger.ps1"
```

That single step: **OBS SaveReplayBuffer** (in-process WebSocket) → **worker HTTP `/replay`** (wait for success) → **scoreboard `replay_on`**.

### Optional: 30-second script-side cooldown (two-step or legacy one-button)

Use this only if you want **ReplayTrove** to enforce cooldown **in addition to** (or instead of) Companion.

- **`scripts/replay_gate_check.ps1`** — run **first**; exits **`0`** if replay is allowed (updates `state/replay_lock.txt`), **`1`** if still inside cooldown (skip step 2), **`2`** if the lock file is unreadable.
- **`scripts/save_replay_and_trigger.ps1`** — run **second**, only when step 1 exited **`0`** (Companion “run if successful” / conditional chain, if your version supports it).
- **`scripts/replay_start_gate.ps1`** — **single** action: runs the gate then the canonical script in a child process; when blocked, still exits **`0`** (legacy) so one-button setups do not show a failure.

### Latency (OBS save vs Companion → OBS)

- **Companion → OBS** (native “Save Replay Buffer” / WebSocket action) is usually **sub‑second**: one long‑lived client, no extra process.
- **`save_replay_and_trigger.ps1`** used to spawn a **second** `powershell.exe` only to run the WebSocket save; that cold start often added **~2–4s** before OBS saw the request. The script now calls the WebSocket **in the same process** as the rest of the pipeline (see `scripts/obs_save_replay_core.ps1`), so OBS save latency should be much closer to a direct Companion action.
- The **full** button still does **OBS save → worker `/replay` (wait) → scoreboard `replay_on`**. Total time includes worker ingest (disk, mux, etc.), not just OBS. For **minimum time-to-save in OBS only**, use **Companion → OBS** for SaveReplay, then **`worker_notify_instant_replay.ps1 -Http`** (or a second button) for worker + scoreboard—or accept that the single canonical script waits for the worker before firing `replay_on` (by design).

---

## Acceptable shortcuts (know what you skip)

| Path | What it does | When it’s OK |
|------|----------------|----------------|
| **`scripts/worker_notify_instant_replay.ps1 -Http`** | **Skip OBS save only:** runs `save_replay_and_trigger.ps1` with **`-SkipObsSave`** — worker HTTP `/replay`, then scoreboard **`replay_on`** on success (same as full pipeline after the buffer is saved). | OBS **Save Replay Buffer** already ran (e.g. separate OBS hotkey). Prefer **`save_replay_and_trigger.ps1`** alone if you want one button to do OBS + worker + scoreboard. |
| **`worker/streamdeck_trigger_replay.bat`** | Runs the **HTTP notify** wrapper above (no OBS save in this file). | Same as row above—Stream Deck “Open” target. |
| **`scripts/send_command.ps1`** with **`replay_on`** / **`replay_off`** | Drops a command file for the **scoreboard only**. | UI / slate control when ingest already happened, or testing. **Does not** save the OBS buffer or run worker processing by itself. |

Port resolution for the notify wrapper: environment `REPLAY_TRIGGER_HTTP_PORT`, else unified settings, else **18765**.

---

## Legacy / emergency / testing only

| Path | Notes |
|------|--------|
| **Trigger file** (`INSTANT_REPLAY_TRIGGER_FILE`, worker background ingest) | **Non-canonical.** See `worker/.env.example` warnings. For recovery, labs, or transitional installs—not for normal “go live” wiring. |
| **`replay_on.vbs` / `toggle_replay.vbs`** | **Do not use for new shortcuts.** Deprecated; they forward to `save_replay_and_trigger.ps1` and log under `state/deprecated_replay_entrypoints.log`. |
| **Command bus `toggle_replay`** | Deprecated action; prefer **`replay_on`** / **`replay_off`**. |

---

## Avoid this (reduces confusion)

- **Wrong HTTP port** (e.g. an old default like 8791). Always match **Control Center** / `config/settings.json`.
- **New VBS replay triggers**—use `.ps1` or documented `.bat` instead.
- **Assuming `send_command replay_on` replaces the full pipeline**—it does not touch OBS save or worker ingest.

---

## Quick checks

1. **Control Center** → System Status → **Replay pipeline readiness** (host, port, reachable).
2. **Logs:** `state/save_replay_and_trigger_log.txt`, `state/worker_notify_instant_replay_log.txt`.
3. After changing the port in JSON, update **Companion / Stream Deck** to the same value and restart services if needed.

---

## Related scripts (wrappers)

- **`scripts/obs_save_replay_and_notify_worker.ps1`** — compatibility wrapper; forwards to **`save_replay_and_trigger.ps1`**. Prefer calling the canonical script directly for new automation.

## Golden appliance profile (copy-paste layout)

For Stream Deck / Companion paths and Tier A vs Tier B buttons, use **`operator-profiles/golden-appliance/README.md`** (`run-full-replay.bat`, `run-replay-off.bat`, optional `run-worker-replay-notify.bat`).

# Golden appliance operator profile (Stream Deck / Companion)

**One known-good default** for wiring replay and related scoreboard actions.  
Canonical behavior is defined in **`docs/operator-replay-trigger-runbook.md`**—read that first for “why,” use this folder for “what to point buttons at.”

There is **no checked-in Stream Deck `.streamDeckProfile` or Companion binary export** (formats churn and embed machine paths). This package is **path-stable within the repo**: thin wrappers + `.bat` files you assign to buttons.

---

## Assumptions (read before go-live)

| Assumption | Detail |
|------------|--------|
| **Repo / install root** | Default docs use `C:\ReplayTrove`. If different, set env **`REPLAYTROVE_ROOT`** to that root for the wrappers, or edit button paths. |
| **Worker HTTP replay** | **`worker.httpReplayTriggerEnabled`** is on; **`worker.httpReplayTriggerPort`** matches every notify path. Stock default port is **`18765`**—confirm in Control Center → System Status. |
| **Launcher / processes** | Worker and scoreboard run under your normal launcher model; golden scripts do not start services. |
| **OBS WebSocket** | Canonical full replay needs OBS reachable with the password/config used by `save_replay_and_trigger.ps1` (unified + env as today). |

**Do not substitute** legacy paths for the standard layout: no **`replay_on.vbs` / `toggle_replay.vbs`**, no **trigger-file ingest** as the primary button, no **`send_command -Action replay_on`** as a replacement for full replay unless you intentionally want scoreboard-only (see runbook).

---

## Standard operator trigger set

Wire **Tier A** on every install. Add **Tier B** only if you **intentionally** split “OBS save buffer” from “notify worker.”

### Tier A — required

| # | Operator label (suggested) | What it runs | Role |
|---|---------------------------|--------------|------|
| 1 | **Replay** (or **Instant replay**) | `run-full-replay.bat` **or** `invoke-full-replay.ps1` | **Full canonical pipeline:** OBS SaveReplayBuffer → worker HTTP `/replay` → scoreboard `replay_on` on success. |
| 2 | **Replay off** | `run-replay-off.bat` **or** `invoke-replay-off.ps1` | **Scoreboard only:** `replay_off` via command bus. Does not run worker ingest. |

### Tier B — optional (split workflow only)

| # | Operator label (suggested) | What it runs | Role |
|---|---------------------------|--------------|------|
| 3 | **Replay: worker notify** (clear label!) | `run-worker-replay-notify.bat` **or** `invoke-worker-replay-notify.ps1` | **After OBS saved elsewhere:** worker HTTP `/replay`, then scoreboard `replay_on` on success. Does not call OBS SaveReplay in this step. |

---

## Paths to use on disk

All paths below assume **`C:\ReplayTrove`**. Change the prefix if needed.

| Artifact | Full path |
|----------|-----------|
| Full replay (Stream Deck “Open”) | `C:\ReplayTrove\operator-profiles\golden-appliance\run-full-replay.bat` |
| Worker notify only | `C:\ReplayTrove\operator-profiles\golden-appliance\run-worker-replay-notify.bat` |
| Replay off | `C:\ReplayTrove\operator-profiles\golden-appliance\run-replay-off.bat` |

PowerShell equivalents (Companion / advanced): same directory, `invoke-*.ps1`.

---

## Stream Deck (Elgato)

1. Add a **System → Open** action (or equivalent “open file”).
2. **Replay:** file = `run-full-replay.bat` (full path above).
3. **Replay off:** file = `run-replay-off.bat`.
4. Optional **Tier B:** `run-worker-replay-notify.bat` only if you use a split workflow.

Use **Open** on the `.bat` so you do not have to embed a long `powershell.exe ...` line.

---

## Bitfocus Companion

Use a **Run / Execute** style action (exact UI depends on Companion version):

- **Program:** `powershell.exe`
- **Arguments (example, full replay):**  
  `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\ReplayTrove\operator-profiles\golden-appliance\invoke-full-replay.ps1"`

Or run the matching **`run-*.bat`** via **`cmd.exe /c`** if your module prefers a single path.

Repeat with `invoke-replay-off.ps1` and, if needed, `invoke-worker-replay-notify.ps1`.

---

## Optional — not part of the golden profile

These are **valid** elsewhere in ReplayTrove but **not** in this default three-button story—add separate buttons only with a written ops reason:

- Score +/- , black screen, encoder controls (`send_command.ps1` with other actions).
- **`send_command -Action replay_on`** (scoreboard-only; misleading as a sole “replay” button).
- **`worker/streamdeck_trigger_replay.bat`** outside this folder (functionally similar to Tier B; golden profile standardizes on `run-worker-replay-notify.bat` for clarity).
- **`obs_save_replay_and_notify_worker.ps1`** (legacy wrapper; golden Tier A uses wrappers → `save_replay_and_trigger.ps1` directly).
- Any **`.vbs`** replay triggers, **trigger-file** worker mode, **`toggle_replay`** command.

---

## Validation checklist

1. Control Center → **Replay pipeline readiness** shows expected **host/port** (port **18765** if default) and reachable **yes** (when worker is up).
2. Press **Replay**: OBS saves buffer, worker processes, scoreboard shows replay (check `state/save_replay_and_trigger_log.txt`).
3. Press **Replay off**: replay UI dismisses; no requirement for worker log lines.
4. If Tier B is wired: confirm **OBS save already happened** before pressing **worker notify**; otherwise use Tier A only.
5. After cloning repo to a non-default drive, set **`REPLAYTROVE_ROOT`** or update all button paths.

---

## File list in this package

| File | Purpose |
|------|---------|
| `README.md` | This installer guide |
| `invoke-full-replay.ps1` | Calls `scripts/save_replay_and_trigger.ps1` |
| `invoke-worker-replay-notify.ps1` | Calls `scripts/worker_notify_instant_replay.ps1 -Http` |
| `invoke-replay-off.ps1` | Calls `scripts/send_command.ps1` → `replay_off` |
| `run-*.bat` | Stream Deck–friendly open targets |

# Booking Overlay Runbook

## What This System Does

The booking overlay system automatically shows full-screen session graphics on the scoreboard monitor based on Pickle Planner booking times:

- **Welcome overlay** near booking start
- **Goodbye overlay** at booking end

It is designed for appliance-style operation: once configured, it runs automatically in the scoreboard app.

## Required Graphic Files

These image files must exist:

- `C:\ReplayTrove\graphics\startsession.png`
- `C:\ReplayTrove\graphics\ENDsession.png`

## Required Environment / Config Values

These values must be set correctly for booking lookups:

- `PICKLE_PLANNER_MATCH_URL`
- `PICKLE_PLANNER_API_KEY`
- `PICKLE_PLANNER_API_KEY_HEADER`
- `CLUB_ID`
- `COURT_ID`

If these are missing or wrong, booking polling will fail and overlays will not trigger automatically.

## Booking Overlay Settings (config/settings.json)

Set under `scoreboard`:

- `bookingOverlayEnabled`  
  Enable/disable booking overlays.
- `bookingOverlayDurationMs`  
  How long overlay stays visible (default: 30000).
- `bookingOverlayPollIntervalSec`  
  Poll interval (default: 1800; aligns to roughly `xx:00` / `xx:30`).
- `bookingOverlaySuppressDuringReplay`  
  If true, defer overlays while replay/lockout is active.
- `bookingOverlayWelcomeImage`  
  Welcome image path.
- `bookingOverlayGoodbyeImage`  
  Goodbye image path.
- `bookingOverlayStatePath`  
  State file path for duplicate prevention.

## Duplicate Prevention (How It Works)

State is persisted at `bookingOverlayStatePath` (default: `state\booking_overlay_state.json`), including:

- active booking id
- last booking that showed welcome
- last booking that showed goodbye
- last seen booking start/end timestamps

This prevents re-showing welcome/goodbye every poll cycle for the same booking.

## Replay-Safe Queueing (How It Works)

If `bookingOverlaySuppressDuringReplay=true` and replay is active, overlay requests are queued instead of shown immediately.

- Queue retries automatically
- Overlay displays after replay/lockout clears
- Prevents booking overlay from interrupting replay UI transitions

## Manual Testing

Run from repo root:

- `.\scripts\test_booking_overlay.ps1 -Mode welcome`
- `.\scripts\test_booking_overlay.ps1 -Mode goodbye`
- `.\scripts\test_booking_overlay.ps1 -Mode inject -BookingId test-123`

Expected:

- Welcome/goodbye modes show immediate full-screen overlay.
- Inject mode simulates booking data and exercises automatic decision logic.

## Troubleshooting

- **Overlay does not appear**
  - Confirm `bookingOverlayEnabled=true`
  - Confirm image paths exist and are readable
  - Check replay is not actively suppressing display
  - Review logs for `booking_overlay_display_error`

- **Wrong court/club booking**
  - Verify `CLUB_ID` and `COURT_ID`
  - Verify `PICKLE_PLANNER_MATCH_URL` points to the correct environment

- **API failure**
  - Check network/API access and key/header values
  - Look for polling warnings; system retries next cycle automatically

- **Graphic path missing**
  - Verify:
    - `C:\ReplayTrove\graphics\startsession.png`
    - `C:\ReplayTrove\graphics\ENDsession.png`
  - Verify `bookingOverlayWelcomeImage` and `bookingOverlayGoodbyeImage` match actual paths

- **Overlay repeats unexpectedly**
  - Inspect `bookingOverlayStatePath` contents
  - Confirm booking IDs from API are stable and not changing format

- **Goodbye overlay does not fire**
  - Confirm booking `end_time` is returned and parseable
  - Confirm local clock/timezone health
  - Confirm duplicate state did not already mark goodbye for that booking

## Logs: Where and What to Search

Check central daily logs under:

- `C:\ReplayTrove\logs\YYYY-MM-DD\scoreboard.jsonl`
- or `C:\ReplayTrove\logs\YYYY-MM-DD\timeline.jsonl`

Search for these events:

- `booking_overlay_poll`
- `booking_overlay_booking_found`
- `booking_overlay_welcome_shown`
- `booking_overlay_goodbye_shown`
- `booking_overlay_skipped_duplicate`
- `booking_overlay_queued_for_replay`
- `booking_overlay_display_error`

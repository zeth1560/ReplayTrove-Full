# ReplayTrove System Layer (`rt_system`)

This folder is a **git-friendly system layer** for ReplayTrove. It keeps operational scripts, stable config, and documentation in one portable location so your desktop and mini PC can share the same FFmpeg behavior.

## Purpose

`rt_system` stores:
- FFmpeg launch scripts for long-form recording
- Environment-style config for capture/encoder settings
- OBS-related notes/config snippets (non-runtime)
- Documentation for setup and operations

## What belongs in git

Keep these tracked:
- `rt_system/ffmpeg/*.bat`
- `rt_system/scripts/*.bat`
- `rt_system/config/*.env` (template-safe values only)
- `rt_system/docs/**`
- `rt_system/obs/**` (docs and non-secret settings exports)

## What does NOT belong in git

Do **not** track:
- Recordings (`*.mp4`, `*.mkv`, etc.)
- Runtime clip folders and processed media
- Logs and temporary files
- Machine-local overrides and secrets (`*.local`, `*.secret`, private tokens)

## Portability model

The portability approach is intentionally boring and reliable:
- Scripts read defaults from `rt_system/config/recording.env`
- Paths and device names are plain text, easy to update per machine
- Runtime output is directed outside `rt_system` to avoid polluting git
- Same folder structure on both machines means low-friction sync through git

## Layout

- `rt_system/ffmpeg` - primary FFmpeg recording scripts
- `rt_system/config` - shared recording configuration
- `rt_system/scripts` - utility and validation scripts
- `rt_system/obs` - OBS integration notes/config exports
- `rt_system/docs` - system docs and operational notes

## First run checklist

1. Open `rt_system/config/recording.env` and set `CAPTURE_DEVICE_NAME` to your DirectShow input name.
2. Confirm `OUTPUT_DIR` points to your preferred long-form recording folder.
3. Run `rt_system/scripts/test_ffmpeg_capture.bat` to verify a 10-second capture.
4. If test looks good, run `rt_system/ffmpeg/record.bat` for long-form recording.

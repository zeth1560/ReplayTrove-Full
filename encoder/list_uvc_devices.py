"""Print UVC / capture devices (DirectShow on Windows, v4l2 on Linux).

Without flags: runs ffmpeg and forwards its output (human-readable, stderr).
With --json: prints a single JSON object to stdout with structured video/audio lists.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from settings import resolve_ffmpeg_path


def _resolve_ffmpeg() -> Path:
    return resolve_ffmpeg_path()


def _ffmpeg_list_args(ff: Path) -> list[str]:
    if sys.platform == "win32":
        return [str(ff), "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"]
    return [str(ff), "-hide_banner", "-f", "v4l2", "-list_devices", "true", "-i", "dummy"]


def _parse_dshow_sectioned(stderr_text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Older ffmpeg: section headers 'DirectShow video devices' / '... audio devices'."""
    video: list[dict[str, str]] = []
    audio: list[dict[str, str]] = []
    section: str | None = None
    device_line = re.compile(r'^\[[^\]]+\]\s+"([^"]+)"\s*$')
    for raw in stderr_text.splitlines():
        line = raw.strip()
        lower = line.lower()
        if "directshow video devices" in lower:
            section = "video"
            continue
        if "directshow audio devices" in lower:
            section = "audio"
            continue
        if "alternative name" in lower:
            continue
        m = device_line.match(line)
        if not m or section is None:
            continue
        name = m.group(1).strip()
        if not name:
            continue
        if section == "video":
            video.append({"name": name})
        else:
            audio.append({"name": name})
    return video, audio


def _parse_dshow_headerless(stderr_text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """FFmpeg ~4.4+ lists dshow devices without section headers; media types are on following lines."""
    video: list[dict[str, str]] = []
    audio: list[dict[str, str]] = []
    name_pat = re.compile(r'^\[[^\]]+\]\s+"([^"]+)"(.*)$')
    lines = stderr_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        m = name_pat.match(raw)
        if not m:
            i += 1
            continue
        name = m.group(1).strip()
        if not name:
            i += 1
            continue
        chunk_parts: list[str] = []
        rest = (m.group(2) or "").strip()
        if rest:
            chunk_parts.append(rest)
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if "alternative name" in nxt.lower():
                i += 1
                break
            if name_pat.match(nxt):
                break
            chunk_parts.append(nxt)
            i += 1
        chunk_l = " ".join(chunk_parts).lower()
        has_video = "video" in chunk_l
        has_audio = "audio" in chunk_l
        if "(none)" in chunk_l and not has_video and not has_audio:
            # Pins could not be enumerated; still surface as both so operators can try.
            has_video = True
            has_audio = True
        if not has_video and not has_audio:
            # Extremely old or unusual logging — still list under both.
            has_video = True
            has_audio = True
        if has_video:
            video.append({"name": name})
        if has_audio:
            audio.append({"name": name})
    return video, audio


def _parse_dshow(stderr_text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    low = stderr_text.lower()
    if "directshow video devices" in low:
        return _parse_dshow_sectioned(stderr_text)
    return _parse_dshow_headerless(stderr_text)


def _parse_v4l2(stderr_text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    video: list[dict[str, str]] = []
    # e.g. [video4linux2,v4l2 @ ...] /dev/video0: UVC Camera
    dev_line = re.compile(r"\]\s+(/dev/video\d+):\s*(.*)$")
    for raw in stderr_text.splitlines():
        m = dev_line.search(raw)
        if not m:
            continue
        dev_path = m.group(1).strip()
        label = m.group(2).strip()
        display = label if label else dev_path
        video.append({"name": display, "devicePath": dev_path})
    return video, []


def list_devices_json(ff: Path) -> dict:
    args = _ffmpeg_list_args(ff)
    r = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stderr = r.stderr or ""
    stdout = r.stdout or ""
    # Some builds log mostly to stdout; always parse both.
    combined = (stderr + "\n" + stdout).strip()
    if sys.platform == "win32":
        video, audio = _parse_dshow(combined)
    else:
        video, audio = _parse_v4l2(combined)

    out: dict = {
        "ok": bool(video or audio),
        "platform": sys.platform,
        "ffmpegPath": str(ff),
        "ffmpegReturnCode": r.returncode,
        "videoDevices": video,
        "audioDevices": audio,
    }
    if not video and not audio:
        tail = (combined or "")[-2000:]
        out["parseNote"] = "No devices parsed; check ffmpeg output (rawExcerpt)."
        out["rawExcerpt"] = tail.strip()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="List UVC / DirectShow / v4l2 capture devices.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON document to stdout (no human ffmpeg stream).",
    )
    parser.add_argument(
        "--ffmpeg",
        metavar="EXE",
        default=None,
        help="FFmpeg executable for device listing (overrides unified config and FFMPEG_PATH).",
    )
    args = parser.parse_args()
    if args.ffmpeg and str(args.ffmpeg).strip():
        ff = Path(str(args.ffmpeg).strip())
    else:
        ff = _resolve_ffmpeg()
    if args.json:
        if not ff.exists():
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "ffmpeg_not_found",
                        "message": f"FFmpeg not found at {ff} (unified obsFfmpegPaths.ffmpegPath, FFMPEG_PATH, or PATH).",
                        "ffmpegPath": str(ff),
                        "videoDevices": [],
                        "audioDevices": [],
                    },
                    indent=2,
                )
            )
            sys.exit(0)
        payload = list_devices_json(ff)
        print(json.dumps(payload, indent=2))
        sys.exit(0)
    if not ff.exists():
        print(f"FFmpeg not found at {ff}", file=sys.stderr)
        sys.exit(2)
    r = subprocess.run(_ffmpeg_list_args(ff))
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()

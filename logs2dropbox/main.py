"""
Mirror ReplayTrove, cleaner, launcher, scoreboard, and OBS logs into Dropbox for remote monitoring.

Watches configured directories (recursively) and copies new/changed files into
a destination root, using separate subfolders per source to avoid name clashes.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import signal
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

DEFAULT_SOURCES: list[tuple[str, str]] = [
    (r"C:\ReplayTrove\logs", "replaytrove"),
    (r"C:\ReplayTrove\cleaner\cleaner-bee.log", "cleaner"),
    (r"C:\ReplayTrove\launcher\logs", "launcher"),
    (r"C:\ReplayTrove\scoreboard\logs", "scoreboard"),
    (r"C:\Users\admin\AppData\Roaming\obs-studio\logs", "obs-studio"),
]
DEFAULT_DEST = r"C:\Users\admin\Dropbox\logs"

logger = logging.getLogger(__name__)


def _iter_files(root: Path) -> Iterator[Path]:
    if root.is_file():
        yield root
        return
    if not root.is_dir():
        return
    for p in root.rglob("*"):
        if p.is_file():
            yield p


def _destination_path(src: Path, watch_root: Path, dest_root: Path, subdir: str) -> Path | None:
    src_resolved = src.resolve(strict=False)
    watch_resolved = watch_root.resolve(strict=False)

    if watch_root.is_file():
        if src_resolved != watch_resolved:
            return None
        rel = Path(watch_root.name)
    else:
        try:
            rel = src_resolved.relative_to(watch_resolved)
        except ValueError:
            return None

    return dest_root / subdir / rel


def _is_skippable_name(name: str) -> bool:
    lower = name.lower()
    if lower.endswith((".tmp", ".temp", ".partial", ".lock")):
        return True
    if name.startswith("~") or name.startswith("."):
        return True
    return False


class DebouncedCopyQueue:
    """
    Debounce filesystem events per path, then copy once the file has settled.

    Log writers often emit many modify events; we wait until ``settle_seconds``
    pass without a new event for that path before copying.
    """

    def __init__(self, settle_seconds: float) -> None:
        self._settle_seconds = max(0.1, settle_seconds)
        self._lock = threading.Lock()
        self._timers: dict[str, threading.Timer] = {}
        self._shutdown = threading.Event()

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()

    def schedule(
        self,
        src_path: Path,
        watch_root: Path,
        dest_root: Path,
        subdir: str,
    ) -> None:
        if self._shutdown.is_set():
            return
        key = str(src_path.resolve(strict=False)).lower()

        def _run() -> None:
            with self._lock:
                self._timers.pop(key, None)
            if self._shutdown.is_set():
                return
            _copy_one(src_path, watch_root, dest_root, subdir)

        with self._lock:
            old = self._timers.pop(key, None)
            if old is not None:
                old.cancel()
            t = threading.Timer(self._settle_seconds, _run)
            self._timers[key] = t
            t.daemon = True
            t.start()


def _copy_one(src: Path, watch_root: Path, dest_root: Path, subdir: str) -> None:
    try:
        if not src.is_file():
            return
        if _is_skippable_name(src.name):
            return
        dest = _destination_path(src, watch_root, dest_root, subdir)
        if dest is None:
            logger.debug("Path outside watch root, skip: %s", src)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".copying")
        for attempt in range(8):
            try:
                shutil.copy2(src, tmp)
                tmp.replace(dest)
                logger.info("Copied %s -> %s", src, dest)
                return
            except OSError as e:
                wait = 0.25 * (2**attempt)
                logger.debug("Copy retry (%s): %s — %s", attempt + 1, src, e)
                time.sleep(min(wait, 4.0))
        logger.warning("Giving up copy after retries: %s", src)
    except Exception:
        logger.exception("Unexpected error copying %s", src)


def _initial_sync(
    watch_root: Path,
    dest_root: Path,
    subdir: str,
    queue: DebouncedCopyQueue,
) -> None:
    if not watch_root.exists():
        logger.warning("Watch path missing (will sync after restart): %s", watch_root)
        return
    for f in sorted(_iter_files(watch_root)):
        if _is_skippable_name(f.name):
            continue
        dest = _destination_path(f, watch_root, dest_root, subdir)
        if dest is None:
            continue
        try:
            if dest.is_file():
                src_mtime = f.stat().st_mtime
                dst_mtime = dest.stat().st_mtime
                if dst_mtime >= src_mtime:
                    continue
        except OSError:
            pass
        queue.schedule(f, watch_root, dest_root, subdir)


class LogMirrorHandler(FileSystemEventHandler):
    def __init__(
        self,
        watch_root: Path,
        dest_root: Path,
        subdir: str,
        queue: DebouncedCopyQueue,
    ) -> None:
        super().__init__()
        self._watch_root = watch_root
        self._dest_root = dest_root
        self._subdir = subdir
        self._queue = queue
        self._watch_file = (
            watch_root.resolve(strict=False) if watch_root.exists() and watch_root.is_file() else None
        )

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        dest = getattr(event, "dest_path", None)
        if dest:
            self._handle(Path(dest))

    def _handle(self, path: Path) -> None:
        if _is_skippable_name(path.name):
            return
        if self._watch_file is not None and path.resolve(strict=False) != self._watch_file:
            return
        self._queue.schedule(path, self._watch_root, self._dest_root, self._subdir)


def _parse_sources(specs: list[str]) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for raw in specs:
        if "=" in raw:
            path_s, tag = raw.split("=", 1)
            path_s, tag = path_s.strip(), tag.strip()
            if not path_s or not tag:
                raise ValueError(f"Invalid source spec (use path=tag): {raw!r}")
            out.append((Path(path_s), tag))
        else:
            p = Path(raw.strip())
            tag = p.name.replace(" ", "_").lower() or "logs"
            out.append((p, tag))
    return out


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mirror log folders into Dropbox")
    p.add_argument(
        "--dest",
        type=Path,
        default=Path(DEFAULT_DEST),
        help=f"Dropbox destination root (default: {DEFAULT_DEST})",
    )
    p.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="PATH=TAG",
        help=(
            "Watch path and subfolder name under dest (repeatable). "
            "Example: --source C:\\ReplayTrove\\logs=replaytrove "
            "Default: built-in ReplayTrove, cleaner, launcher, scoreboard, and OBS paths."
        ),
    )
    p.add_argument(
        "--settle",
        type=float,
        default=2.0,
        help="Seconds to wait after last event before copying a file (default: 2)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.sources:
        try:
            sources = _parse_sources(args.sources)
        except ValueError as e:
            logger.error("%s", e)
            return 2
    else:
        sources = [(Path(p), tag) for p, tag in DEFAULT_SOURCES]

    dest_root: Path = args.dest
    dest_root.mkdir(parents=True, exist_ok=True)

    queue = DebouncedCopyQueue(settle_seconds=args.settle)
    observers: list[Observer] = []

    for watch_root, subdir in sources:
        _initial_sync(watch_root, dest_root, subdir, queue)
        handler = LogMirrorHandler(watch_root, dest_root, subdir, queue)
        obs = Observer()
        schedule_path = watch_root if watch_root.is_dir() else watch_root.parent
        if schedule_path.is_dir():
            obs.schedule(handler, str(schedule_path), recursive=watch_root.is_dir())
            obs.start()
            observers.append(obs)
            logger.info("Watching %s -> %s/%s/", watch_root, dest_root, subdir)
        else:
            logger.warning("Skipping missing path (not a file or directory): %s", watch_root)

    if not observers:
        logger.error("No valid watch directories; exiting.")
        return 1

    stop = threading.Event()

    def _stop(*_a: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while not stop.is_set():
            time.sleep(0.5)
    finally:
        queue.shutdown()
        for o in observers:
            o.stop()
            o.join(timeout=5.0)
        logger.info("Stopped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

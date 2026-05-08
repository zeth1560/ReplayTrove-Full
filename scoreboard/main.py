"""Entry point: logging, settings, startup validation, Tk root, scoreboard app."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCOREBOARD_PROJECT_DIR = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scoreboard.config.settings import load_settings
from scoreboard.logging_config import configure_logging
from scoreboard.startup_validation import (
    log_pilot_diagnostics_summary,
    validate_screen_dimensions,
    validate_startup_critical,
)
from scoreboard.app import ScoreboardApp


def main() -> None:
    log = logging.getLogger("scoreboard.main")
    try:
        # Always load scoreboard/.env from this script's folder — cwd may be ReplayTrove root or elsewhere.
        env_file = str(_SCOREBOARD_PROJECT_DIR / ".env")
        settings = load_settings(env_file if Path(env_file).is_file() else ".env")
    except Exception:
        logging.basicConfig(level=logging.INFO)
        log.exception("Failed to load settings; exiting")
        sys.exit(1)

    configure_logging(
        logging.DEBUG if settings.scoreboard_debug else logging.INFO,
        log_file=settings.scoreboard_log_file or None,
        central_logs_root=Path(settings.central_logs_root),
    )

    validate_startup_critical(settings)

    root = tk.Tk()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    validate_screen_dimensions(screen_w, screen_h)

    log_pilot_diagnostics_summary(
        settings,
        screen_width=screen_w,
        screen_height=screen_h,
    )

    try:
        ScoreboardApp(root, settings=settings)
    except Exception:
        log.exception("Failed to start scoreboard UI")
        root.destroy()
        sys.exit(1)

    root.mainloop()


if __name__ == "__main__":
    main()

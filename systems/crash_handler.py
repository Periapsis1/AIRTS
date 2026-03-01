"""Crash handler — logs unhandled exceptions to the logs/ directory."""
from __future__ import annotations
import os
import traceback
from datetime import datetime


_LOG_DIR = "logs"


def log_crash(exc: BaseException, context: str = "") -> str:
    """Write a crash log and return the filepath.

    Parameters
    ----------
    exc : BaseException
        The exception that was caught.
    context : str
        A short label like "game", "replay", or "app" indicating where
        the crash happened.

    Returns
    -------
    str
        Path to the written log file.
    """
    os.makedirs(_LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tag = f"_{context}" if context else ""
    filename = f"crash{tag}_{ts}.log"
    filepath = os.path.join(_LOG_DIR, filename)

    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"AIRTS Crash Report\n")
        f.write(f"Time: {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"Context: {context or 'unknown'}\n")
        f.write(f"{'=' * 60}\n\n")
        f.writelines(tb)

    return filepath

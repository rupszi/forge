"""Logging configuration for Forge.

Single entry point: ``setup_logging()``. Configures the stdlib logger to:

  1. Emit JSON-structured records to stderr at INFO+ for live tailing.
  2. Persist a rotating file at ``.forge/forge.log`` (5 MB × 3 backups)
     for post-mortem inspection.
  3. **Apply the RedactionFilter** (ADR-017) at every record boundary so
     credentials echoed into log messages get scrubbed before they hit
     stderr or the on-disk file.
  4. Route the special ``forge.silent`` logger (used by ``safety.silent_catch``)
     at WARNING+ so deliberately-swallowed exceptions are still grep-able
     in the audit log.

We deliberately use stdlib ``logging`` — not structlog or loguru — so we
stay within the original two-pip-deps rule (ADR-008 documented the
relaxation; the spirit still applies — keep dep gravity low). JSON
formatting is done with a tiny custom Formatter subclass; no extra dep.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import FORGE_DIR
from .redact import RedactionFilter


class JsonFormatter(logging.Formatter):
    """Tiny JSON formatter — one line per record, ISO-8601 timestamp.

    Keys we always emit: ``ts``, ``lvl``, ``mod``, ``msg``. We don't emit
    ``args`` separately because by the time the record reaches us the
    ``RedactionFilter`` has already mutated msg+args; we just call
    ``record.getMessage()`` to format the final string.

    Why a custom class instead of ``python-json-logger``: that's a third
    pip dep. JSON formatting is 8 lines.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "mod": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(
    *,
    level: int = logging.INFO,
    console: bool = True,
    file: bool = True,
    log_dir: str | None = None,
) -> None:
    """Configure root logger handlers.

    Idempotent — calling twice doesn't double-attach handlers (we clear the
    root logger's handler list first).

    Parameters
    ----------
    level
        Root logger level. INFO by default; CLI flag ``--verbose`` would
        bump to DEBUG.
    console
        Attach a stderr handler.
    file
        Attach a rotating file handler at ``<log_dir>/forge.log``.
    log_dir
        Override location; defaults to ``.forge/`` per ADR-007.
    """
    root = logging.getLogger()
    # Clear any default handlers to make this idempotent.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    formatter = JsonFormatter()
    redaction = RedactionFilter()

    if console:
        # Use stderr for logs (stdout reserved for CLI command output).
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redaction)
        console_handler.setLevel(level)
        root.addHandler(console_handler)

    if file:
        target_dir = log_dir or FORGE_DIR
        try:
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                os.path.join(target_dir, "forge.log"),
                maxBytes=5_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(redaction)
            file_handler.setLevel(level)
            root.addHandler(file_handler)
        except OSError as e:
            # If we can't write the log file (permissions, missing dir
            # outside the current cwd), don't crash — just lose file
            # logging. The console handler still works.
            root.warning("setup_logging: file handler unavailable: %s", e)

    # Ensure forge.silent (used by safety.silent_catch) inherits the same
    # filter+formatter via the root logger's handlers; explicit setLevel
    # so silent_catch warnings always make it through.
    silent = logging.getLogger("forge.silent")
    silent.setLevel(logging.WARNING)
    silent.propagate = True  # bubbles to root, which has the redaction filter

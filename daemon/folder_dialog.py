"""Native folder-picker dialog, opened by the daemon on the user's machine.

Browsers can't return a real server-side path from a folder chooser, but the
daemon is local — so it pops the OS-native dialog (macOS Finder via
``osascript``; Linux via ``zenity`` / ``kdialog`` / ``qarma``) and hands the
chosen absolute path back to the dashboard over the WebSocket.

The dialog is a deliberate user action, so the chosen path is trusted (unlike a
typed path, which the WS layer still scopes to home/cwd).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from collections.abc import Awaitable, Callable

# User interaction can take a while; give it a generous window before giving up.
DIALOG_TIMEOUT = 300

Runner = Callable[..., Awaitable[tuple[int, str, str]]]


async def _default_runner(cmd: list[str], timeout: int = DIALOG_TIMEOUT) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


def _dialog_command(
    platform: str | None = None, which: Callable[[str], str | None] = shutil.which
) -> list[str] | None:
    """Build the native folder-chooser argv for this OS, or None if unavailable."""
    platform = platform or sys.platform
    if platform == "darwin":
        return [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Select a project folder")',
        ]
    # Linux / other unix — try the common GTK/Qt dialog helpers in order.
    if which("zenity"):
        return ["zenity", "--file-selection", "--directory", "--title=Select a project folder"]
    if which("kdialog"):
        return ["kdialog", "--getexistingdirectory", os.path.expanduser("~")]
    if which("qarma"):
        return ["qarma", "--file-selection", "--directory", "--title=Select a project folder"]
    return None


async def pick_folder(
    runner: Runner = _default_runner,
    platform: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> dict:
    """Pop the native folder dialog. Returns ``{ok, path?|cancelled?|error?}``."""
    cmd = _dialog_command(platform, which)
    if cmd is None:
        return {
            "ok": False,
            "error": "no folder-picker dialog available — install zenity or kdialog",
        }
    try:
        code, out, _err = await runner(cmd)
    except (TimeoutError, OSError) as e:
        return {"ok": False, "error": str(e)}
    out = out.strip()
    if code != 0 or not out:
        return {"ok": False, "cancelled": True}
    path = out.splitlines()[0].strip().rstrip("/")
    return {"ok": True, "path": path}

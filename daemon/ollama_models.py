"""List locally-installed Ollama models for the model picker (M5)."""

from __future__ import annotations

import shutil
import subprocess


def installed_models() -> list[dict]:
    """Return ``[{name, size}]`` for every model Ollama has pulled.

    Empty list if Ollama isn't installed or the call fails — the UI then shows
    a "pull models" hint instead of a dropdown.
    """
    if not shutil.which("ollama"):
        return []
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_ollama_list(out.stdout)


def parse_ollama_list(stdout: str) -> list[dict]:
    """Parse ``ollama list`` table output into ``[{name, size}]`` (pure)."""
    models: list[dict] = []
    lines = stdout.splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        # SIZE is two tokens like "4.7 GB"; it sits after NAME and ID.
        size = ""
        if len(parts) >= 4:
            size = f"{parts[2]} {parts[3]}"
        models.append({"name": name, "size": size})
    return models

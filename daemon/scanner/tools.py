"""Detect which CLIs are available on PATH."""

import shutil

TOOL_LIST = ["gh", "supabase", "vercel", "stripe", "playwright", "docker", "kubectl"]


def detect_tools() -> dict[str, bool]:
    """Check which CLIs are available on PATH."""
    tools = {}
    for tool in TOOL_LIST:
        tools[tool] = shutil.which(tool) is not None
    return tools

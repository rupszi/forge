"""Knowledge-base content guard — reject prompt-injection shapes (M3, G-AGT-4).

KB items are one-line imperative statements injected verbatim into agent
prompts. The 2026-06-02 audit flagged that a malicious or scraped item could
carry a code fence or a fake system header to break out of its context block.
This guard rejects those shapes at the ``add`` boundary so the KB can only ever
hold benign one-liners.
"""

from __future__ import annotations

import re

# One-liners only — anything this long is structured content, not a gotcha.
MAX_KB_CONTENT_LEN = 500

_INJECTION_PATTERNS = [
    re.compile(r"```"),  # markdown code fence (breaks out of the context block)
    re.compile(r"^\s*(---|\+\+\+)\s*$", re.MULTILINE),  # YAML/TOML front matter
    re.compile(r"<\|im_(start|end)\|>", re.IGNORECASE),  # chat-template markers
    re.compile(r"\b(ignore|disregard)\b.{0,30}\b(previous|prior|above|all)\b", re.IGNORECASE),
    re.compile(r"^\s*system\s*:", re.IGNORECASE | re.MULTILINE),  # fake system turn
    re.compile(r"#{1,6}\s*system\b", re.IGNORECASE),  # "## SYSTEM" header
]


class KBContentRejected(ValueError):
    """Raised when KB content looks like a prompt-injection payload."""


def validate_kb_content(content: str) -> None:
    """Raise ``KBContentRejected`` if ``content`` isn't a safe one-liner.

    Checks (in order): null bytes, length cap, then structural / instruction
    injection patterns. Returns ``None`` on success.
    """
    if "\x00" in content:
        msg = "KB content contains null bytes"
        raise KBContentRejected(msg)
    if len(content) > MAX_KB_CONTENT_LEN:
        msg = f"KB content too long ({len(content)} > {MAX_KB_CONTENT_LEN}); items are one-liners"
        raise KBContentRejected(msg)
    for pat in _INJECTION_PATTERNS:
        if pat.search(content):
            msg = f"KB content rejected: matches injection pattern {pat.pattern!r}"
            raise KBContentRejected(msg)

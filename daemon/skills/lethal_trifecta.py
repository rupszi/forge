"""Lethal-trifecta capability graph (per docs/SECURITY_AUDIT.md Layer 3).

Willison's "lethal trifecta" (2025) names the agent-tool combinations
that lead to the worst zero-click data-exfil chains: when a single
session has tools that together provide

    (private data access) + (untrusted input) + (external egress)

…the agent — even without intent — can be steered into copying secrets
out via the egress channel based on instructions hidden in the untrusted
input.

We refuse the combination at scheduler level. This is enforced before
the model sees any of the tools, so model jailbreaks can't override it.

Reference: https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/

Real-world incidents this addresses:
- Microsoft 365 Copilot "EchoLeak" (CVE-2025-32711, 2025)
- ChatGPT connectors / Salesforce-Slack chains (2025)
- GitHub Copilot Chat image-rendering exfil (2024)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityProfile:
    """What a connector / skill / tool does in trifecta-relevant terms.

    The flags are the *minimum* set that captures the trifecta. Each flag
    must be conservative: when in doubt, mark True.
    """

    # Reads "private" data: env vars containing secrets, the user's filesystem
    # outside the worktree, KB items marked confidential, etc.
    reads_private: bool

    # Reads "untrusted" data: web fetches, user-provided URL contents, MCP
    # responses from servers the user hasn't pinned, repo files (because they
    # may have been crafted by an attacker — see Pillar Security 2025).
    reads_untrusted: bool

    # Writes to "external" destinations: any tool that posts data to a URL
    # outside localhost / the project's own infrastructure. Includes email,
    # webhook, file upload, generic HTTP POST to public endpoints.
    writes_external: bool


def is_blocked_combination(profiles: list[CapabilityProfile]) -> str | None:
    """Return a refusal reason if the combined profile forms the trifecta.

    Forge calls this with the union of capability profiles for every
    connector / skill that the planner / generator wants to invoke in
    one session. If the combined profile is the trifecta, we refuse the
    composition — even if each individual tool is safe.

    Returns ``None`` when the combination is OK to proceed.
    """
    if not profiles:
        return None

    has_private = any(p.reads_private for p in profiles)
    has_untrusted = any(p.reads_untrusted for p in profiles)
    has_egress = any(p.writes_external for p in profiles)

    if has_private and has_untrusted and has_egress:
        # Identify which profiles contributed to make the rejection actionable.
        contributors = {
            "private": [i for i, p in enumerate(profiles) if p.reads_private],
            "untrusted": [i for i, p in enumerate(profiles) if p.reads_untrusted],
            "egress": [i for i, p in enumerate(profiles) if p.writes_external],
        }
        return (
            "Refused: lethal-trifecta tool combination "
            "(private + untrusted + egress). "
            f"Contributing profile indices: {contributors}. "
            "See docs/SECURITY_AUDIT.md Layer 3."
        )
    return None


# Default profiles for built-in connectors. Plugin authors override via
# manifest metadata (planned: ``[capabilities].trifecta`` block).
BUILTIN_PROFILES: dict[str, CapabilityProfile] = {
    "git": CapabilityProfile(reads_private=False, reads_untrusted=False, writes_external=False),
    "github_mcp": CapabilityProfile(
        reads_private=False, reads_untrusted=True, writes_external=True
    ),
    "vercel_mcp": CapabilityProfile(
        reads_private=True, reads_untrusted=False, writes_external=True
    ),
    "supabase_mcp": CapabilityProfile(
        reads_private=True, reads_untrusted=False, writes_external=True
    ),
    "postgres_mcp": CapabilityProfile(
        reads_private=True, reads_untrusted=False, writes_external=False
    ),
    "stripe_mcp": CapabilityProfile(
        reads_private=True, reads_untrusted=False, writes_external=True
    ),
    "sendgrid": CapabilityProfile(reads_private=False, reads_untrusted=False, writes_external=True),
    "web_research": CapabilityProfile(
        reads_private=False, reads_untrusted=True, writes_external=False
    ),
    "slack_mcp": CapabilityProfile(reads_private=False, reads_untrusted=True, writes_external=True),
    "discord_mcp": CapabilityProfile(
        reads_private=False, reads_untrusted=True, writes_external=True
    ),
    "linear_mcp": CapabilityProfile(
        reads_private=False, reads_untrusted=True, writes_external=True
    ),
}

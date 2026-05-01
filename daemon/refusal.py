"""Structured refusal templates — Sprint 7.10.

When ``daemon.safety.is_destructive`` matches OR a hook returns
``{"action": "block"}``, Forge needs to surface the rejection back to
the agent in a way the agent can recover from. A silent block leaves
the model confused (it sees its tool call vanished); a structured
refusal tells it exactly why and what to try next.

The format is deliberately Claude-Code-shaped so models trained on
Claude's tool-use traces recognize it:

    The previous tool call was refused because it matched destructive-op rule:
      pattern: \\brm\\s+-rf\\s+/(?!\\w)
      reason: rm -rf / — catastrophic
      severity: block

    If you genuinely need to perform this operation, ask the user to
    switch to bypass mode (⌘ M, then 5).

Refusal text is stable, not templated per-call — same input → same
output. Stable text keeps prompt caches warm across revisions of a
sprint that hits the same rule twice.
"""

from __future__ import annotations

from .hooks import HookResult
from .safety import DestructiveOp


def from_destructive_op(op: DestructiveOp) -> str:
    """Render a structured refusal for a ``DestructiveOp`` match.

    The agent sees this in its tool-result slot. The intent is for the
    model to plan an alternative approach (e.g. confirm with user, scope
    narrower, or ask the user to flip mode) rather than retry blindly.
    """
    return (
        "The previous tool call was refused because it matched "
        f"destructive-op rule:\n"
        f"  pattern: {op.pattern}\n"
        f"  reason: {op.reason}\n"
        f"  severity: {op.severity}\n"
        "\n"
        "If you genuinely need to perform this operation, ask the user "
        "to switch to bypass mode (⌘ M, then 5) or relax the rule via "
        "`.forge/safety.toml`. Do not retry the same command verbatim — "
        "the rule will fire again."
    )


def from_hook_block(result: HookResult, hook_event: str = "PreToolUse") -> str:
    """Render a structured refusal for a hook's blocking result.

    ``hook_event`` names the lifecycle point so the agent can distinguish
    a PreToolUse refusal (don't run the tool) from a PostToolUse one
    (the tool ran but a check after it failed — different recovery).
    """
    reason = result.reason or "(no reason provided)"
    extra_lines: list[str] = []
    for key in sorted(result.extra):
        value = result.extra[key]
        extra_lines.append(f"  {key}: {value}")
    extras_block = ("\n" + "\n".join(extra_lines)) if extra_lines else ""

    return (
        f"The previous tool call was refused by a {hook_event} hook:\n"
        f"  reason: {reason}\n"
        f"  exit_code: {result.exit_code}"
        f"{extras_block}\n"
        "\n"
        "Hooks are user-supplied scripts the project owner installed. "
        "Address the reason directly (e.g. fix the lint, satisfy the "
        "policy) — bypass mode does NOT skip user hooks. Adjust the "
        "approach and try again."
    )


def from_capability_violation(host: str, allowlist: list[str]) -> str:
    """Render a structured refusal for an egress filter rejection."""
    al = ", ".join(allowlist) if allowlist else "(empty — deny-all)"
    return (
        "The previous network request was refused by the capability "
        "egress filter:\n"
        f"  host: {host}\n"
        f"  allow-list: {al}\n"
        "\n"
        "Plugins can only reach hosts declared in their manifest's "
        "[capabilities].network. To widen the scope, edit the manifest "
        "and re-approve via `forge connectors add` — this triggers the "
        "capability-change re-approval prompt before the new hosts apply."
    )


def from_skill_tampered(plugin_kind: str, plugin_name: str, expected: str, got: str) -> str:
    """Render a structured refusal for a plugin hash mismatch."""
    return (
        "The plugin invocation was refused because the on-disk hash "
        "differs from the pinned digest:\n"
        f"  plugin: {plugin_kind}:{plugin_name}\n"
        f"  expected sha256: {expected[:16]}…\n"
        f"  got sha256:      {got[:16]}…\n"
        "\n"
        "The plugin directory was modified after approval. Either revert "
        "the change, or re-approve with `forge connectors add` (which "
        "triggers the capability-change prompt). The previous version "
        "stays pinned until you decide."
    )

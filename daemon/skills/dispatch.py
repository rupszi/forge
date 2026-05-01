"""Plugin dispatcher — the integration point for skills / connectors / LLM adapters.

This is what Sprint 6.1.1 wires up. Each call to ``dispatch_plugin`` ties
together the five primitives that previously sat on shelves:

    1. ``daemon/connectors/registry.py`` / ``daemon/skills/registry.py``
       — load + parse manifest, recompute SHA-256 of the directory.
    2. ``daemon/skills/lock.py::PluginsLock.verify``
       — refuse to run if the directory hash drifted from the pinned digest
       (raises ``SkillTampered``).
    3. ``daemon/skills/lethal_trifecta.is_blocked_combination``
       — refuse compositions that the model could be steered into using
       for zero-click data-exfil (private + untrusted + egress).
    4. ``daemon/skills/runtime.py::run_skill``
       — actually spawn the subprocess with capability env scoped to the
       manifest (``FORGE_NETWORK_ALLOWLIST``, ``FORGE_FS_WRITABLE``).
    5. ``ForgeDB.record_invocation_start`` / ``record_invocation_finish``
       — Layer 7 append-only audit log; one row before spawn, one after.

The dispatcher is the *only* legitimate path from a sprint / generator
into a plugin's code. Tools that bypass it (importing a plugin's
plugin.py directly from daemon code) skip the security model — that
would be a bug, caught by the dispatcher's audit-log schema only being
satisfied through ``dispatch_plugin``.

Sprint 6.1.1 acceptance gate:
  - "A sprint that references a skill spawns a subprocess with the
    manifest's capability env" → ``dispatch_plugin`` does exactly that.
  - The path is callable from the scheduler (re-exported in
    ``daemon.scheduler``) so the agent loop will pick it up in Sprint 6.4
    when the reference connectors land.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db import ForgeDB
from .lethal_trifecta import CapabilityProfile, is_blocked_combination
from .lock import PluginsLock, SkillTampered
from .runtime import SandboxResult, run_skill

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    """Outcome of a single ``dispatch_plugin`` call.

    Always populated even when the dispatcher refused to spawn — the
    caller (CLI / scheduler) inspects ``ok`` + ``error`` to surface the
    refusal reason. ``sandbox_result`` is None iff the dispatcher
    refused before spawn (e.g., SkillTampered).
    """

    ok: bool
    invocation_id: str
    plugin_kind: str
    plugin_name: str
    error: str | None = None
    sandbox_result: SandboxResult | None = None
    capability_violations: list[str] | None = None


def _build_capabilities_dict(manifest: Any) -> dict[str, Any]:
    """Extract the capability fields from any manifest dataclass.

    Skill / connector / LLM manifests share enough field names that
    duck-typing here is fine — we read by attribute and skip any field
    the manifest doesn't expose. The dict produced is what gets pinned
    in the lock and what gets logged to the audit row.
    """
    return {
        "network": list(getattr(manifest, "network", []) or []),
        "filesystem": list(getattr(manifest, "filesystem", []) or []),
        "exec": list(getattr(manifest, "exec", []) or []),
        "secrets_read": list(getattr(manifest, "secrets_read", []) or []),
    }


async def dispatch_plugin(
    *,
    kind: str,  # 'skill' | 'connector' | 'llm'
    name: str,
    plugin_path: Path,
    manifest: Any,
    manifest_sha256: str,
    args: list[str] | None = None,
    db: ForgeDB,
    lock: PluginsLock,
    session_id: str | None = None,
    sprint_id: str | None = None,
    cwd: Path | None = None,
    extra_profiles: list[CapabilityProfile] | None = None,
) -> DispatchResult:
    """The single legitimate entry point to plugin code.

    Parameters
    ----------
    kind
        ``"skill"``, ``"connector"`` or ``"llm"`` — namespaces the lock
        key and the audit row's ``plugin_kind``.
    name
        Plugin name (matches manifest.toml ``[plugin].name``).
    plugin_path
        Directory the plugin lives in.
    manifest
        Parsed manifest object (SkillManifest / ConnectorManifest /
        LLMManifest). Read by attribute.
    manifest_sha256
        Hash computed at load time. The dispatcher verifies it against
        the pinned hash.
    args
        Optional extra CLI args passed to the entry script.
    db
        ForgeDB used for the append-only audit log.
    lock
        PluginsLock for hash + capability verification.
    session_id, sprint_id
        Optional correlation IDs for the audit row.
    cwd
        Working directory for the spawned subprocess. Defaults to
        ``plugin_path``; the scheduler typically passes the worktree
        path so the plugin can read the working tree.
    extra_profiles
        Trifecta profiles for *other* tools active in this session — the
        dispatcher unions them with this plugin's profile so a composition
        that forms the trifecta is rejected even if no single tool does.

    Returns
    -------
    ``DispatchResult`` — never raises on capability violations / tampered
    state; surfaces them as ``ok=False`` + ``error=...`` + a logged
    audit row. Raises only on programmer error (bad arg types).
    """
    invocation_id = os.urandom(8).hex()
    plugin_version = getattr(manifest, "version", "")
    args = args or []

    # ── Layer 3 — manifest hash verification ─────────────────────────────
    #
    # If the on-disk hash differs from what we approved, we refuse to
    # spawn. The audit log records the attempt with the *current* hash
    # so the trail still exists.
    try:
        lock.verify(kind, name, manifest_sha256)
    except SkillTampered as exc:
        # Audit the refusal so a tampering attempt is visible in the log.
        db.record_invocation_finish(
            invocation_id=invocation_id,
            plugin_kind=kind,
            plugin_name=name,
            plugin_version=plugin_version,
            manifest_sha256=manifest_sha256,
            sprint_id=sprint_id,
            session_id=session_id,
            capabilities=None,
            duration_seconds=0.0,
            exit_code=None,
            ok=False,
            error=f"SkillTampered: {exc}",
            capability_violations=["hash mismatch"],
        )
        return DispatchResult(
            ok=False,
            invocation_id=invocation_id,
            plugin_kind=kind,
            plugin_name=name,
            error=str(exc),
            capability_violations=["hash mismatch"],
        )

    # ── Layer 3 cont. — lethal-trifecta gate ─────────────────────────────
    #
    # Build a CapabilityProfile for *this* plugin from its declared scopes:
    # any non-empty ``network`` (and the host being external) → writes_external.
    # The profile is conservative — when in doubt, mark True.
    declared_caps = _build_capabilities_dict(manifest)
    plugin_profile = CapabilityProfile(
        # Reads "private" only if it asked for secrets the runtime would
        # filter through (any non-empty secrets_read).
        reads_private=bool(declared_caps["secrets_read"]),
        # Reads "untrusted" if it has filesystem write to the worktree
        # (worktree contents may have been crafted by an attacker — see
        # Pillar Security 2025) OR it has network capability that could
        # fetch external content.
        reads_untrusted=bool(declared_caps["filesystem"]) or bool(declared_caps["network"]),
        # Writes externally if it has any network scope (egress).
        writes_external=bool(declared_caps["network"]),
    )
    profiles = [plugin_profile] + (extra_profiles or [])
    refusal = is_blocked_combination(profiles)
    if refusal:
        db.record_invocation_finish(
            invocation_id=invocation_id,
            plugin_kind=kind,
            plugin_name=name,
            plugin_version=plugin_version,
            manifest_sha256=manifest_sha256,
            sprint_id=sprint_id,
            session_id=session_id,
            capabilities=declared_caps,
            duration_seconds=0.0,
            exit_code=None,
            ok=False,
            error=f"LethalTrifecta: {refusal}",
            capability_violations=["lethal-trifecta"],
        )
        return DispatchResult(
            ok=False,
            invocation_id=invocation_id,
            plugin_kind=kind,
            plugin_name=name,
            error=refusal,
            capability_violations=["lethal-trifecta"],
        )

    # ── Layer 7 start row ─────────────────────────────────────────────────
    db.record_invocation_start(
        invocation_id=invocation_id,
        plugin_kind=kind,
        plugin_name=name,
        plugin_version=plugin_version,
        manifest_sha256=manifest_sha256,
        sprint_id=sprint_id,
        session_id=session_id,
        capabilities=declared_caps,
        args=args,
    )

    # ── Layers 1, 2, 4, 5, 6 — sandbox runtime ───────────────────────────
    entry_script = getattr(manifest, "entry_script", "scripts/main.py")
    cpu_seconds = int(getattr(manifest, "cpu_seconds", 60) or 60)
    wall_seconds = int(getattr(manifest, "wall_seconds", 120) or 120)
    memory_mb = int(getattr(manifest, "memory_mb", 1024) or 1024)

    sandbox_result = await run_skill(
        skill_path=plugin_path,
        entry_script=entry_script,
        args=list(args),
        secrets_allowed=declared_caps["secrets_read"],
        network_allowlist=declared_caps["network"],
        fs_writable=declared_caps["filesystem"],
        cpu_seconds=cpu_seconds,
        wall_seconds=wall_seconds,
        memory_mb=memory_mb,
        cwd=cwd or plugin_path,
    )

    # ── Layer 7 finish row ───────────────────────────────────────────────
    db.record_invocation_finish(
        invocation_id=invocation_id,
        plugin_kind=kind,
        plugin_name=name,
        plugin_version=plugin_version,
        manifest_sha256=manifest_sha256,
        sprint_id=sprint_id,
        session_id=session_id,
        capabilities=declared_caps,
        duration_seconds=sandbox_result.duration_seconds,
        exit_code=sandbox_result.exit_code,
        ok=sandbox_result.ok,
        error=sandbox_result.error,
        capability_violations=sandbox_result.capability_violations or None,
    )

    return DispatchResult(
        ok=sandbox_result.ok,
        invocation_id=invocation_id,
        plugin_kind=kind,
        plugin_name=name,
        error=sandbox_result.error,
        sandbox_result=sandbox_result,
        capability_violations=sandbox_result.capability_violations or None,
    )

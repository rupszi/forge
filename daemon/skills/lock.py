"""Plugin-manifest hash pinning — ``.forge/plugins.lock``.

Layer 3 of the seven-layer security model: signed-manifest + hash-pinning.
Once the user approves a plugin (via the wizard or `forge connectors add`),
its directory contents are hashed and the digest is recorded in
``.forge/plugins.lock``. Every subsequent dispatch re-hashes the directory
and compares — a mismatch raises ``SkillTampered`` and refuses to run.

This catches:

  - A plugin file silently swapped on disk (supply-chain attack post-install)
  - A plugin author shipping a benign manifest then auto-updating the
    scripts/ folder server-side
  - A user accidentally editing a vendored plugin and re-running without
    going through the approval flow

The lock format is TOML, hand-readable so users can audit it in a PR:

    schema_version = 1

    [plugins."skill:csv-cleaner"]
    sha256 = "abc...64hex"
    version = "0.2.0"
    approved_at = "2026-05-01T..."
    approved_capabilities = { network = [...], filesystem = [...] }

Lock keys are namespaced by plugin kind (``"skill:..."`` / ``"connector:..."`` /
``"llm:..."``) because a connector and a skill can both be named ``github``
without collision in the same lock file.

The lock file lives at the project level, not user-global: that means a
clone of the repo carries the lock with it (read-only for collaborators,
mutable for the user via the approval flow). Per ADR-007 the file does
NOT contain credentials — only structural metadata.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillTampered(RuntimeError):
    """Raised when a plugin's on-disk hash differs from the pinned digest.

    Subclass of ``RuntimeError`` so user code that wraps the dispatcher
    in a try/except RuntimeError still catches it for cleanup, but tests
    and the dispatcher's specific handler can target the exact class.
    """


@dataclass
class LockEntry:
    """One row in the lock file, keyed by ``"<kind>:<name>"``."""

    sha256: str
    version: str = ""
    approved_at: str = ""
    # Snapshot of the manifest's [capabilities] block at approval time.
    # Used by the wizard's re-approval flow (Sprint 6.1.5) to diff the
    # *currently declared* caps against the *previously approved* caps —
    # any expansion requires explicit re-approval.
    approved_capabilities: dict[str, Any] = field(default_factory=dict)


class PluginsLock:
    """In-memory representation of ``.forge/plugins.lock``.

    Reads on init (silently empty if the file is absent — a fresh project
    has no pinned plugins yet). Writes are explicit via ``save()`` so the
    caller controls when the user-visible file changes.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, LockEntry] = {}
        self._loaded = False
        self.load()

    # ---- key construction ----

    @staticmethod
    def make_key(kind: str, name: str) -> str:
        """Compose the per-plugin key. Kind is one of ``skill`` / ``connector`` / ``llm``."""
        if kind not in ("skill", "connector", "llm"):
            raise ValueError(f"unknown plugin kind: {kind!r}")
        return f"{kind}:{name}"

    # ---- I/O ----

    def load(self) -> None:
        """Re-read from disk. Idempotent."""
        self._entries.clear()
        if not self.path.is_file():
            self._loaded = True
            return

        try:
            import tomllib
        except ImportError:  # Python 3.10
            import tomli as tomllib  # type: ignore[import-not-found,no-redef]

        try:
            with self.path.open("rb") as f:
                data = tomllib.load(f)
        except (OSError, ValueError) as e:
            logger.warning("plugins.lock unreadable (%s); treating as empty", e)
            self._loaded = True
            return

        # Schema version check — refuse to load a newer schema we don't
        # understand. Older code reading a future lock could silently
        # mis-validate, so fail loud.
        schema = data.get("schema_version", 1)
        if schema > self.SCHEMA_VERSION:
            raise ValueError(
                f"plugins.lock schema_version={schema} is newer than this Forge "
                f"build (supports {self.SCHEMA_VERSION}). Upgrade Forge or "
                f"regenerate the lock from a checkout that wrote it."
            )

        plugins = data.get("plugins", {})
        for key, entry_data in plugins.items():
            self._entries[key] = LockEntry(
                sha256=entry_data.get("sha256", ""),
                version=entry_data.get("version", ""),
                approved_at=entry_data.get("approved_at", ""),
                approved_capabilities=entry_data.get("approved_capabilities", {}),
            )
        self._loaded = True

    def save(self) -> None:
        """Persist to disk in deterministic key order."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = [
            "# Forge plugin lock file. Generated by `forge connectors add` and",
            "# `forge skills install`. Pins each plugin's directory hash so",
            "# silent on-disk modification is detected at dispatch time.",
            "# Hand-edit only if you understand the consequences.",
            "",
            f"schema_version = {self.SCHEMA_VERSION}",
            "",
        ]
        for key in sorted(self._entries):
            entry = self._entries[key]
            lines.append(f'[plugins."{key}"]')
            lines.append(f'sha256 = "{entry.sha256}"')
            if entry.version:
                lines.append(f'version = "{entry.version}"')
            if entry.approved_at:
                lines.append(f'approved_at = "{entry.approved_at}"')
            if entry.approved_capabilities:
                lines.append('[plugins."' + key + '".approved_capabilities]')
                for cap_key in sorted(entry.approved_capabilities):
                    cap_value = entry.approved_capabilities[cap_key]
                    if isinstance(cap_value, list):
                        # All-string lists rendered as TOML arrays of strings.
                        quoted = ", ".join(f'"{v}"' for v in cap_value)
                        lines.append(f"{cap_key} = [{quoted}]")
                    elif isinstance(cap_value, bool):
                        lines.append(f"{cap_key} = {str(cap_value).lower()}")
                    elif isinstance(cap_value, (int, float)):
                        lines.append(f"{cap_key} = {cap_value}")
                    else:
                        lines.append(f'{cap_key} = "{cap_value}"')
            lines.append("")
        self.path.write_text("\n".join(lines))

    # ---- queries ----

    def get(self, kind: str, name: str) -> LockEntry | None:
        return self._entries.get(self.make_key(kind, name))

    def has(self, kind: str, name: str) -> bool:
        return self.make_key(kind, name) in self._entries

    def all_entries(self) -> dict[str, LockEntry]:
        return dict(self._entries)

    # ---- mutations ----

    def pin(
        self,
        kind: str,
        name: str,
        *,
        sha256: str,
        version: str = "",
        approved_capabilities: dict[str, Any] | None = None,
        approved_at: str = "",
    ) -> LockEntry:
        """Record a plugin's approved hash + capabilities.

        Replaces any existing entry — caller is responsible for the
        re-approval flow (wizard prompt) when the existing entry's
        capabilities differ from the new ones.
        """
        from datetime import datetime, timezone

        if not approved_at:
            approved_at = datetime.now(timezone.utc).isoformat()

        entry = LockEntry(
            sha256=sha256,
            version=version,
            approved_at=approved_at,
            approved_capabilities=dict(approved_capabilities or {}),
        )
        self._entries[self.make_key(kind, name)] = entry
        return entry

    def unpin(self, kind: str, name: str) -> bool:
        """Remove an entry (e.g. when uninstalling). Returns True iff present."""
        key = self.make_key(kind, name)
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    # ---- verification ----

    def verify(self, kind: str, name: str, current_sha256: str) -> None:
        """Raise ``SkillTampered`` iff the current SHA differs from the pinned one.

        Three failure modes, each gets a distinct message:
          - plugin not in lock at all  → SkillTampered("not pinned")
          - SHA mismatch               → SkillTampered("hash mismatch ...")

        Caller (the dispatcher) catches and surfaces the exception with
        a refusal-to-run message; the user re-runs the approval flow to
        re-pin if the change was intentional.
        """
        entry = self.get(kind, name)
        if entry is None:
            raise SkillTampered(
                f"plugin {kind}:{name!r} is not pinned in {self.path}. "
                "Run `forge connectors add` / `forge skills install` to approve."
            )
        if entry.sha256 != current_sha256:
            raise SkillTampered(
                f"plugin {kind}:{name!r} hash mismatch: "
                f"expected {entry.sha256[:12]}…, got {current_sha256[:12]}…. "
                "The plugin directory was modified after approval. "
                "Refusing to run; re-approve with `forge connectors add` if intentional."
            )

    def diff_capabilities(
        self, kind: str, name: str, current_capabilities: dict[str, Any]
    ) -> dict[str, tuple[Any, Any]] | None:
        """Return a per-key (old, new) diff, or None if approved == current.

        Used by the wizard re-approval flow (Sprint 6.1.5): when a
        plugin's manifest still hashes to the same digest (no file
        changed) but somehow declares new capabilities, that's a
        contradictory state we should surface. More importantly, it's
        called BEFORE re-pinning a changed hash — to ask the user
        "you're approving a hash bump; here are the capability changes".
        """
        entry = self.get(kind, name)
        if entry is None:
            return None
        approved = entry.approved_capabilities
        diff: dict[str, tuple[Any, Any]] = {}
        all_keys = set(approved) | set(current_capabilities)
        for key in sorted(all_keys):
            old = approved.get(key)
            new = current_capabilities.get(key)
            if old != new:
                diff[key] = (old, new)
        return diff or None

    # ---- introspection (for forge connectors list / skills list) ----

    def to_dict(self) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "plugins": {key: asdict(entry) for key, entry in self._entries.items()},
        }


def default_lock_path(project_path: Path) -> Path:
    """The standard location: ``<project>/.forge/plugins.lock``."""
    return project_path / ".forge" / "plugins.lock"

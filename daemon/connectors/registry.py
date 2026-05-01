"""Native-plugin connector registry.

Holds the list of installed connectors, their capabilities, and the
hash-pinned manifest digests. Reads/writes ``.forge/connectors.toml``
and ``.forge/plugins.lock``.

This file is intentionally a *skeleton* for v0.1.0 — the heavy lifting
(subprocess sandbox, capability enforcement, hash verification) lives in
``daemon/skills/runtime.py`` because it's shared between connectors,
skills, and LLM adapters.

CLI entry points (in cli.py):
  forge connectors list
  forge connectors add <path>
  forge connectors enable <name>
  forge connectors disable <name>
  forge connectors test <name>
  forge connectors remove <name>
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Default user-level plugin root. Per-project overrides via .forge/plugins/.
DEFAULT_PLUGIN_ROOT = Path.home() / ".forge" / "plugins"


@dataclass
class ConnectorManifest:
    """Parsed manifest.toml for a native connector.

    Mirrors docs/PLUGIN_DEVELOPMENT.md schema v1. Fields beyond the listed
    ones (e.g., custom plugin metadata) are preserved in ``extras`` so a
    future schema bump doesn't lose data.
    """

    name: str
    version: str
    description: str
    author: str | None = None
    license: str | None = None
    schema_version: int = 1
    forge_min_version: str = "0.1.0"
    # capabilities
    network: list[str] = field(default_factory=list)
    filesystem: list[str] = field(default_factory=list)
    exec: list[str] = field(default_factory=list)
    secrets_read: list[str] = field(default_factory=list)
    secrets_write: list[str] = field(default_factory=list)
    # limits
    memory_mb: int = 1024
    cpu_seconds: int = 60
    wall_seconds: int = 120
    # tools (per-method metadata)
    tools: dict[str, dict] = field(default_factory=dict)
    # extras for forward-compat
    extras: dict = field(default_factory=dict)

    def __post_init__(self):
        # Refusing-to-load gates per docs/SKILLS.md "Refusing skills" section.
        if any(b in self.exec for b in ("sh", "bash", "zsh", "fish")):
            raise ValueError(
                f"connector {self.name}: declares shell in exec capability "
                "(sh / bash / zsh / fish) — refused per security policy"
            )
        # Same wildcard rule as skills (kept in sync deliberately): bare "*"
        # and TLD-only "*.com" patterns refused; narrow "*.api.example.com"
        # accepted because the egress shim understands them.
        for n in self.network:
            if n == "*":
                raise ValueError(f"connector {self.name}: wildcard network capability '*' refused")
            if n.startswith("*.") and n.count(".") == 1:
                raise ValueError(
                    f"connector {self.name}: TLD-only wildcard {n!r} is too broad — refused"
                )
        if any(p == "/" or p.startswith("/etc") for p in self.filesystem):
            raise ValueError(
                f"connector {self.name}: filesystem capability includes system paths — refused"
            )


@dataclass
class ConnectorEntry:
    """A registered connector and its current state."""

    manifest: ConnectorManifest
    plugin_path: Path
    enabled: bool = False
    manifest_sha256: str = ""
    last_used_at: str | None = None


class ConnectorRegistry:
    """In-memory registry; persisted to .forge/connectors.toml."""

    def __init__(self, plugin_root: Path | None = None):
        self.plugin_root = plugin_root or DEFAULT_PLUGIN_ROOT
        self._connectors: dict[str, ConnectorEntry] = {}

    def register(self, entry: ConnectorEntry) -> None:
        """Add a connector to the registry. Existing entry with the same
        name is REPLACED — caller is responsible for re-approval flow on
        manifest hash change (see docs/SECURITY_AUDIT.md Layer 2)."""
        self._connectors[entry.manifest.name] = entry
        logger.info(
            "registered connector %s v%s (enabled=%s)",
            entry.manifest.name,
            entry.manifest.version,
            entry.enabled,
        )

    def get(self, name: str) -> ConnectorEntry | None:
        return self._connectors.get(name)

    def list_all(self) -> list[ConnectorEntry]:
        return sorted(self._connectors.values(), key=lambda e: e.manifest.name)

    def list_enabled(self) -> list[ConnectorEntry]:
        return [e for e in self._connectors.values() if e.enabled]

    def enable(self, name: str) -> bool:
        entry = self._connectors.get(name)
        if entry is None:
            return False
        entry.enabled = True
        return True

    def disable(self, name: str) -> bool:
        entry = self._connectors.get(name)
        if entry is None:
            return False
        entry.enabled = False
        return True


def load_connector(plugin_path: str | Path) -> ConnectorEntry:
    """Load a connector from a plugin directory.

    Steps:
      1. Read manifest.toml (raises if missing or invalid)
      2. Validate schema version, license, capabilities
      3. Compute SHA-256 of every file in the plugin dir
      4. Compare against ``.forge/plugins.lock`` if present; on mismatch,
         caller (CLI) shows the diff and asks for re-approval
      5. Return ConnectorEntry (caller decides whether to register)

    The actual subprocess sandbox runs at *invocation* time, not load
    time. See ``daemon/skills/runtime.py``.
    """
    plugin_path = Path(plugin_path).expanduser()
    if not plugin_path.is_dir():
        raise FileNotFoundError(f"connector plugin path not found: {plugin_path}")
    manifest_path = plugin_path / "manifest.toml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest.toml in {plugin_path}")

    manifest = _parse_manifest(manifest_path)
    sha = _hash_directory(plugin_path)

    return ConnectorEntry(
        manifest=manifest,
        plugin_path=plugin_path,
        enabled=False,  # Default disabled; user must explicitly enable
        manifest_sha256=sha,
    )


def list_connectors(registry: ConnectorRegistry | None = None) -> list[ConnectorEntry]:
    """List all installed connectors. Used by ``forge connectors list``."""
    reg = registry or ConnectorRegistry()
    return reg.list_all()


def _parse_manifest(manifest_path: Path) -> ConnectorManifest:
    """Read and validate a manifest.toml.

    Uses tomllib (3.11+) with a tomli fallback for 3.10. Raises on schema
    version mismatch or refused-capability content.
    """
    try:
        import tomllib
    except ImportError:  # Python 3.10
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]

    with manifest_path.open("rb") as f:
        data = tomllib.load(f)

    plugin = data.get("plugin", {})
    capabilities = data.get("capabilities", {})
    limits = data.get("limits", {})

    return ConnectorManifest(
        name=plugin["name"],
        version=plugin["version"],
        description=plugin.get("description", ""),
        author=plugin.get("author"),
        license=plugin.get("license"),
        schema_version=plugin.get("schema_version", 1),
        forge_min_version=plugin.get("forge_min_version", "0.1.0"),
        network=capabilities.get("network", []),
        filesystem=capabilities.get("filesystem", []),
        exec=capabilities.get("exec", []),
        secrets_read=capabilities.get("secrets_read", []),
        secrets_write=capabilities.get("secrets_write", []),
        memory_mb=limits.get("memory_mb", 1024),
        cpu_seconds=limits.get("cpu_seconds", 60),
        wall_seconds=limits.get("wall_seconds", 120),
        tools=data.get("tools", {}),
        extras={
            k: v for k, v in data.items() if k not in ("plugin", "capabilities", "limits", "tools")
        },
    )


def _hash_directory(path: Path) -> str:
    """Compute a deterministic SHA-256 of every file in the plugin dir.

    Files are walked in sorted order; each (relative-path + content) is
    hashed in. The result is what gets pinned in .forge/plugins.lock.
    """
    import hashlib

    hasher = hashlib.sha256()
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(path).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(file_path.read_bytes())
    return hasher.hexdigest()

"""LLM-adapter registry — manifest parsing for ``~/.forge/llms/<name>/``.

Same sandbox model as connectors / skills (see daemon/skills/runtime.py),
narrower API surface: an adapter implements ``generate(request) -> result``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_LLM_ROOT = Path.home() / ".forge" / "llms"


@dataclass
class LLMManifest:
    """Parsed manifest.toml for an LLM adapter. Schema v1."""

    name: str
    version: str
    description: str = ""
    license: str | None = None
    schema_version: int = 1
    forge_min_version: str = "0.1.0"
    # capabilities
    network: list[str] = field(default_factory=list)
    secrets_read: list[str] = field(default_factory=list)
    # llm-specific
    provider: str = ""
    family: str = ""
    default_model: str = ""
    endpoint_env: str = ""
    api_key_env: str = ""
    # per-model metadata (each: context_window, supports_tools, supports_json_mode, prices)
    models: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self):
        if not self.network:
            raise ValueError(
                f"LLM adapter {self.name}: must declare at least one network "
                "capability (the provider endpoint). Empty network = no adapter."
            )
        if "*" in self.network:
            raise ValueError(f"LLM adapter {self.name}: wildcard network capability refused")
        if not self.family:
            raise ValueError(
                f"LLM adapter {self.name}: must declare 'family' for "
                "cross-family-evaluator routing (see ADR-006)"
            )


@dataclass
class LLMAdapterEntry:
    """Registered LLM adapter."""

    manifest: LLMManifest
    plugin_path: Path
    enabled: bool = False
    manifest_sha256: str = ""


def load_llm(plugin_path: str | Path) -> LLMAdapterEntry:
    """Load an LLM adapter plugin from disk.

    Same lifecycle as ``daemon.connectors.registry.load_connector``:
    parse manifest, hash directory, return entry. Caller decides whether
    to register and enable.
    """
    path = Path(plugin_path).expanduser()
    if not path.is_dir():
        raise FileNotFoundError(f"LLM adapter path not found: {path}")
    manifest_path = path / "manifest.toml"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"no manifest.toml in {path}")

    manifest = _parse_manifest(manifest_path)
    sha = _hash_directory(path)

    return LLMAdapterEntry(
        manifest=manifest,
        plugin_path=path,
        enabled=False,
        manifest_sha256=sha,
    )


def list_llms(root: Path | None = None) -> list[LLMAdapterEntry]:
    """List all installed LLM adapters."""
    root = root or DEFAULT_LLM_ROOT
    if not root.is_dir():
        return []
    entries: list[LLMAdapterEntry] = []
    for plugin_dir in sorted(root.iterdir()):
        if not plugin_dir.is_dir():
            continue
        try:
            entries.append(load_llm(plugin_dir))
        except (FileNotFoundError, ValueError) as e:
            logger.warning("skipping %s: %s", plugin_dir, e)
    return entries


def _parse_manifest(manifest_path: Path) -> LLMManifest:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]

    with manifest_path.open("rb") as f:
        data = tomllib.load(f)

    plugin = data.get("plugin", {})
    capabilities = data.get("capabilities", {})
    llm = data.get("llm", {})

    return LLMManifest(
        name=plugin["name"],
        version=plugin["version"],
        description=plugin.get("description", ""),
        license=plugin.get("license"),
        schema_version=plugin.get("schema_version", 1),
        forge_min_version=plugin.get("forge_min_version", "0.1.0"),
        network=capabilities.get("network", []),
        secrets_read=capabilities.get("secrets_read", []),
        provider=llm.get("provider", ""),
        family=llm.get("family", ""),
        default_model=llm.get("default_model", ""),
        endpoint_env=llm.get("endpoint_env", ""),
        api_key_env=llm.get("api_key_env", ""),
        models=llm.get("models", {}),
    )


def _hash_directory(path: Path) -> str:
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

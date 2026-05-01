"""Skill registry — manifest parsing and capability validation.

Mirrors connectors/registry.py shape but tuned for the skill format
(SKILL.md + manifest.toml + scripts/ + references/ + examples/).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SKILL_ROOT = Path.home() / ".forge" / "skills"


@dataclass
class SkillManifest:
    """Parsed manifest.toml for a skill. Schema v1."""

    name: str
    version: str
    description: str = ""
    author: str | None = None
    license: str | None = None
    schema_version: int = 1
    forge_min_version: str = "0.1.0"
    when_to_use: str = ""  # natural-language; planner reads verbatim
    # capabilities
    network: list[str] = field(default_factory=list)
    filesystem: list[str] = field(default_factory=list)
    exec: list[str] = field(default_factory=list)
    secrets_read: list[str] = field(default_factory=list)
    # limits
    memory_mb: int = 1024
    cpu_seconds: int = 60
    wall_seconds: int = 120
    # script entry
    entry_script: str = "scripts/main.py"

    def __post_init__(self):
        # Same refusing-to-load gates as connectors. See
        # docs/SKILLS.md "Refusing skills" for rationale.
        bad_shells = ("sh", "bash", "zsh", "fish")
        for b in bad_shells:
            if b in self.exec:
                raise ValueError(
                    f"skill {self.name}: declares shell '{b}' in exec — "
                    "refused per security policy (skills cannot ask for shells)"
                )
        # Refuse bare "*" (allow-anything) and TLD-only wildcards like
        # "*.com" / "*.org" / "*.io" (too broad). Narrow subdomain
        # wildcards like "*.python.org" / "*.github.io" are accepted —
        # the egress shim (forge_plugin_api/http.py) understands them
        # and they map to a finite set of hosts under a single org.
        for n in self.network:
            if n == "*":
                raise ValueError(f"skill {self.name}: wildcard network capability — refused")
            if n.startswith("*.") and n.count(".") == 1:
                raise ValueError(
                    f"skill {self.name}: TLD-only wildcard {n!r} is too broad — refused. "
                    "Use a narrower subdomain wildcard like '*.python.org'."
                )
        for fs in self.filesystem:
            if fs == "/" or fs.startswith("/etc") or fs.startswith("/sys"):
                raise ValueError(
                    f"skill {self.name}: filesystem capability includes system path — refused"
                )


@dataclass
class SkillEntry:
    """An installed skill and its current state."""

    manifest: SkillManifest
    skill_path: Path
    skill_md: str = ""  # contents of SKILL.md (first 1000 chars used in planner prompt)
    enabled: bool = False
    manifest_sha256: str = ""
    last_invoked_at: str | None = None


def load_skill(skill_path: str | Path) -> SkillEntry:
    """Load a skill from disk.

    Steps:
      1. Verify SKILL.md exists (it's the planner-facing interface)
      2. Parse manifest.toml (raises on capability violations)
      3. Compute SHA-256 of every file in the skill dir
      4. Read SKILL.md for the planner's ``when_to_use`` body
      5. Return SkillEntry; caller decides whether to install
    """
    path = Path(skill_path).expanduser()
    if not path.is_dir():
        raise FileNotFoundError(f"skill path not found: {path}")

    skill_md_path = path / "SKILL.md"
    if not skill_md_path.is_file():
        raise FileNotFoundError(
            f"no SKILL.md in {path} — required for planner-readable description"
        )

    manifest_path = path / "manifest.toml"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"no manifest.toml in {path} — refused. "
            "Use `forge skills import-claude` to wrap a Claude-Code-only skill."
        )

    manifest = _parse_manifest(manifest_path)
    sha = _hash_directory(path)
    skill_md = skill_md_path.read_text(encoding="utf-8")

    return SkillEntry(
        manifest=manifest,
        skill_path=path,
        skill_md=skill_md,
        enabled=False,  # default disabled until user explicitly enables
        manifest_sha256=sha,
    )


def _parse_manifest(manifest_path: Path) -> SkillManifest:
    """Read manifest.toml and construct a SkillManifest."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]

    with manifest_path.open("rb") as f:
        data = tomllib.load(f)

    plugin = data.get("plugin", {})
    skill = data.get("skill", {})
    capabilities = data.get("capabilities", {})
    limits = data.get("limits", {})

    return SkillManifest(
        name=plugin["name"],
        version=plugin["version"],
        description=plugin.get("description", ""),
        author=plugin.get("author"),
        license=plugin.get("license"),
        schema_version=plugin.get("schema_version", 1),
        forge_min_version=plugin.get("forge_min_version", "0.1.0"),
        when_to_use=skill.get("when_to_use", ""),
        network=capabilities.get("network", []),
        filesystem=capabilities.get("filesystem", []),
        exec=capabilities.get("exec", []),
        secrets_read=capabilities.get("secrets_read", []),
        memory_mb=limits.get("memory_mb", 1024),
        cpu_seconds=limits.get("cpu_seconds", 60),
        wall_seconds=limits.get("wall_seconds", 120),
        entry_script=skill.get("entry_script", "scripts/main.py"),
    )


def _hash_directory(path: Path) -> str:
    """Deterministic SHA-256 of every file in the skill dir."""
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

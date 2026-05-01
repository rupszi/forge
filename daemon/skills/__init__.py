"""Skills system: Claude-Code-compatible skills with sandbox.

A *skill* is a self-contained directory with a SKILL.md (planner-readable
instruction-bundle), a manifest.toml (capabilities), and optional
scripts/references/examples. The planner can pull a skill into the
generator's prompt when its ``when_to_use`` matches the task.

Every skill invocation runs in the seven-layer sandbox documented in
docs/SKILLS.md:

  1. Subprocess isolation
  2. Capability declaration
  3. Signed manifests + pinned hashes
  4. Path scoping
  5. Resource limits
  6. Network egress filtering
  7. Append-only audit log

The runtime is shared with connectors and LLM adapters because the security
model is the same — only the surface API differs.

CLI entry points (in cli.py):
  forge skills install <source>
  forge skills list
  forge skills enable <name>
  forge skills disable <name>
  forge skills test <name>
  forge skills update <name>
  forge skills audit <name>
  forge skills remove <name>
  forge skills import-claude <path>
"""

from __future__ import annotations

from .lethal_trifecta import is_blocked_combination
from .lock import LockEntry, PluginsLock, SkillTampered, default_lock_path
from .registry import SkillEntry, SkillManifest, load_skill
from .runtime import SandboxResult, run_skill

__all__ = [
    "LockEntry",
    "PluginsLock",
    "SandboxResult",
    "SkillEntry",
    "SkillManifest",
    "SkillTampered",
    "default_lock_path",
    "is_blocked_combination",
    "load_skill",
    "run_skill",
]

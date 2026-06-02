"""Local model provisioning — `forge models pull` with a disk guard (M1, G-RAM-2).

Pulling the default local lineup can be tens of GB. On a disk-constrained
machine an unguarded pull fills the volume and bricks the session. ``plan_pull``
is a pure function (size in, decision out) so the refuse/allow logic is
testable without touching the disk or Ollama; the CLI layer does the actual
``ollama pull`` only when the plan says ok.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field

from .config import (
    LOCAL_BACKUP_MID_MODEL,
    LOCAL_CODE_MODEL,
    LOCAL_EMBED_MODEL,
    LOCAL_PLAN_MODEL,
    model_disk_headroom_gb,
)


@dataclass(frozen=True)
class ModelSpec:
    """A model and its approximate on-disk size (Q4-ish) in GB."""

    name: str
    size_gb: float


# The default local lineup pulled on first run. Sizes are conservative Q4
# estimates. This set is a *complete offline harness*: an orchestrator/planner,
# a coder (generator), a DIFFERENT-family evaluator (so cross-family grading
# works with no network — ADR-006), and an embedding model for memory recall.
# Total ~14.6 GB. Larger generators (qwen2.5-coder:14b/32b) are pulled on
# demand by the classifier/budget, not up front.
DEFAULT_MODEL_SET: list[ModelSpec] = [
    ModelSpec(LOCAL_PLAN_MODEL, 4.7),  # orchestrator (qwen2.5:7b)
    ModelSpec(LOCAL_CODE_MODEL, 4.7),  # generator (qwen2.5-coder:7b)
    ModelSpec(LOCAL_BACKUP_MID_MODEL, 4.9),  # cross-family evaluator (llama3.1:8b)
    ModelSpec(LOCAL_EMBED_MODEL, 0.3),  # embeddings (nomic-embed-text)
]


@dataclass
class PullPlan:
    to_pull: list[ModelSpec] = field(default_factory=list)
    total_gb: float = 0.0
    free_gb: float = 0.0
    headroom_gb: float = 0.0
    ok: bool = True
    refused_reason: str | None = None


def free_disk_gb(path: str = ".") -> float:
    """Free space (GB) on the volume containing ``path``."""
    return shutil.disk_usage(path).free / (1024**3)


# Explicit footprints for models whose name doesn't carry a parameter count.
_KNOWN_SIZES_GB: dict[str, float] = {m.name: m.size_gb for m in DEFAULT_MODEL_SET}
_PARAM_GB_FACTOR = 0.6  # ~Q4 bytes-per-param → GB per billion params
_DEFAULT_MODEL_GB = 8.0
_param_re = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.IGNORECASE)


def estimate_size_gb(model: str) -> float:
    """Best-effort RAM/disk footprint (GB) for a model, for the pool budget.

    Order: explicit known size → embedding heuristic → parameter-count parse
    (``...27b`` → ~16 GB at Q4) → conservative default. The pool accepts an
    explicit ``size_gb`` override, so this is only the fallback estimate.
    """
    if model in _KNOWN_SIZES_GB:
        return _KNOWN_SIZES_GB[model]
    name = model.lower()
    if "embed" in name:
        return 0.3
    m = _param_re.search(name)
    if m:
        return round(float(m.group(1)) * _PARAM_GB_FACTOR, 2)
    return _DEFAULT_MODEL_GB


def plan_pull(
    models: list[ModelSpec],
    free_gb: float,
    headroom_gb: float | None = None,
    present: set[str] | None = None,
) -> PullPlan:
    """Decide whether pulling ``models`` is safe.

    Refuses if downloading the not-yet-present models would leave less than
    ``headroom_gb`` free. Already-present models don't count toward the size.
    """
    if headroom_gb is None:
        headroom_gb = model_disk_headroom_gb()
    present = present or set()

    to_pull = [m for m in models if m.name not in present]
    total = round(sum(m.size_gb for m in to_pull), 4)
    plan = PullPlan(
        to_pull=to_pull,
        total_gb=total,
        free_gb=free_gb,
        headroom_gb=headroom_gb,
    )

    remaining_after = free_gb - total
    if remaining_after < headroom_gb:
        plan.ok = False
        plan.refused_reason = (
            f"pulling {total:.1f} GB would leave {remaining_after:.1f} GB free, "
            f"below the {headroom_gb:.1f} GB headroom. Free space, raise "
            f"FORGE_MODEL_DISK_HEADROOM_GB, or set OLLAMA_MODELS to an external volume."
        )
    return plan

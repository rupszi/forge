# SWE-bench Verified harness for Forge

This directory holds the Phase 2 Week 7 deliverable: an adapter that wraps
[Princeton's SWE-bench Verified](https://www.swebench.com/) benchmark with
Forge's planner/generator/evaluator pipeline.

## What this is

A skeleton that lets us:
1. Load SWE-bench task instances.
2. Map each task to a Forge sprint contract.
3. Aggregate per-task results into a subset score.
4. **Enforce the Week-8 kill criterion** ([ADR-015](../../docs/DECISIONS.md#adr-015--week-8-swe-bench-verified-30-on-50-task-subset--hard-kill-criterion)): ≥30% on a 50-task subset → ship; <30% → pivot or shut down.

## Metric tiers & profiles

A bare resolve-rate percentage is neither trustworthy (n=50 is small) nor enough
to justify Forge's three-agent thesis. Metrics are grouped into **tiers**
(`eval/swebench/tiers.py`):

| Tier | What it tells you |
|---|---|
| **1 GATE** | resolve rate + 95% Wilson CI (point AND lower-bound vs the 30% bar) |
| **2 VALIDITY** | patch-apply / empty-patch / harness-error / PASS_TO_PASS regression rates |
| **3 THESIS** | single-agent **baseline delta** + evaluator false-approve / precision / recall |
| **4 COST** | tokens, wall-clock, $ — total and per resolved task |
| **5 DETERMINISM** | resolve-rate variance across repeated runs |

Tiers differ in **cost**: 1/2/4 are aggregations of a single run; Tier 3's
baseline delta needs a *second* run; Tier 5 needs *N* runs. So users pick a
**profile** (a dropdown in the UI, `--profile` on the CLI) rather than ticking
arbitrary tiers:

| Profile | Tiers | Runs | When |
|---|---|---|---|
| `gate` | 1, 2 | 1× | the minimal go/no-go |
| `diagnostic` | 1, 2, 3, 4 | 1× | same cost as gate; adds evaluator + cost diagnostics |
| `baseline` | 1, 2, 3, 4 | ~2× | measures three-agent-vs-single-agent delta |
| `full` | 1–5 | ~N× | most thorough (variance + baseline) |

```bash
forge bench --list-profiles               # show profiles, their tiers + cost
forge bench --profile baseline --dry-run  # preview the plan (offline)
forge bench --profile gate --subset eval/swebench/django_50.jsonl   # live (needs Docker)
```

The UI dropdown is populated by the `bench.profiles` WebSocket message
(`tiers.profile_options()`); see `docs/WEBSOCKET_PROTOCOL.md`. Metrics are
computed by `metrics.compute_metrics(subset, tiers, ...)` and rendered by
`report.render_markdown` — only the selected tiers appear.

## What this is NOT (yet)

The actual `real_forge_runner` is a stub. Real execution requires:
- Docker (for SWE-bench's Conda-based test environments)
- Ollama with the [ADR-003 model lineup](../../docs/DECISIONS.md#adr-003--open-weight-model-defaults-post-apr-2223-releases) pulled
- ~30 GB free SSD per concurrent task
- GPU (M-series 24GB+ recommended)

The skeleton's interface is unit-testable today; wiring the real Docker invocation is a follow-up.

## Recommended subset

Per [BUILD_PLAN.md Week 7](../../docs/BUILD_PLAN.md#week-7--swe-bench-harness-setup-25-h), the **django subset** (50 tasks) is the target. Reasons:
- Well-isolated tests (no GPU/network needed for verification)
- Fast test execution (most tasks finish in <2 min)
- Representative of real Python work
- Same subset many other research papers cite, so comparisons are easy

## Building the django subset

```bash
# 1. Download SWE-bench Verified
wget https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/test.jsonl

# 2. Filter to django, take 50
jq -c 'select(.repo == "django/django")' test.jsonl | head -50 > django_50.jsonl

# 3. Verify
wc -l django_50.jsonl  # should print 50
```

## Running (when wired)

```python
from eval.swebench.adapter import load_tasks_from_jsonl, real_forge_runner, run_subset

tasks = load_tasks_from_jsonl("eval/swebench/django_50.jsonl")
result = run_subset(tasks, forge_runner=real_forge_runner)
print(result.summary())
# →  SWE-bench subset: 17/50 passed (34.0%)
#       failed: 30, errored: 3
#       kill_criterion (≥30%): PASS
```

## CI integration

Not in CI by default — too expensive. Run locally on demand:

```bash
RUN_SWEBENCH_SMOKE=1 bash scripts/pre-push.sh
```

(See `scripts/pre-push.sh` — the `RUN_SWEBENCH_SMOKE` env var triggers a 5-task smoke run if you've wired `eval/swebench/smoke.py`.)

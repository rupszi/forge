"""CLI commands for forge."""

import argparse
import asyncio
import contextlib
import os
import shutil
import subprocess
from pathlib import Path

from .budget import BudgetController
from .config import DB_PATH, FORGE_DIR, WS_PORT
from .db import ForgeDB
from .memory.knowledge import KnowledgeBase
from .scanner.project import scan_project


def _get_db() -> ForgeDB:
    return ForgeDB(DB_PATH)


def _launch_ui(ui_dir: Path | None = None):
    """Start the Next.js dashboard as a managed subprocess (one-command serve).

    Degrades gracefully — if the ``ui/`` directory, its dependencies, or a
    package manager are missing, returns ``None`` and the daemon runs alone.
    Returns the ``Popen`` handle so ``cmd_serve`` can stop it on shutdown.
    """
    if ui_dir is None:
        ui_dir = Path(__file__).resolve().parent.parent / "ui"
    if not ui_dir.is_dir():
        print("  UI: ui/ not found — running daemon only.")
        return None
    if not (ui_dir / "node_modules").is_dir():
        print("  UI: dependencies not installed (cd ui && pnpm install) — running daemon only.")
        return None
    pm = "pnpm" if shutil.which("pnpm") else ("npm" if shutil.which("npm") else None)
    if pm is None:
        print("  UI: no pnpm/npm on PATH — running daemon only.")
        return None
    cmd = [pm, "dev"] if pm == "pnpm" else ["npm", "run", "dev"]
    try:
        proc = subprocess.Popen(cmd, cwd=str(ui_dir))
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  UI: failed to start ({e}) — running daemon only.")
        return None
    print(f"  UI: starting dashboard with {pm} → http://localhost:3000")
    return proc


def _stop_ui(proc) -> None:
    """Terminate the UI subprocess cleanly (used on daemon shutdown)."""
    if proc is None:
        return
    with contextlib.suppress(Exception):
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _port_in_use(host: str, port: int) -> bool:
    """True if ``host:port`` can't be bound (something is already listening)."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _pid_on_port(port: int) -> int | None:
    """PID of the process listening on ``port`` (via lsof), or None."""
    try:
        out = subprocess.run(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    return pids[0] if pids else None


def _run_async(coro):
    """Run an async function from sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def cmd_init(args):
    """Scan project, create .forge/, display context."""
    path = os.getcwd()
    ctx = _run_async(scan_project(path))
    db = _get_db()

    # Add .forge/ to .gitignore if not already there
    gitignore = os.path.join(path, ".gitignore")
    if os.path.exists(gitignore):
        content = open(gitignore).read()
        if ".forge/" not in content:
            with open(gitignore, "a") as f:
                f.write("\n.forge/\n")
    else:
        with open(gitignore, "w") as f:
            f.write(".forge/\n")

    kb = KnowledgeBase(db)

    print(f"\nForge initialized in {path}\n")
    if ctx.is_git:
        print(
            f"  Git:        {ctx.default_branch} branch"
            + (f", {ctx.remote_url}" if ctx.remote_url else "")
        )
    if ctx.language:
        stack = ctx.framework or ctx.language
        print(f"  Stack:      {stack}" + (f" + {ctx.language.title()}" if ctx.framework else ""))
    if ctx.has_claude:
        print(
            f"  Claude:     CLAUDE.md {'found' if ctx.claude_md else 'not found'}"
            + f", {len(ctx.claude_rules)} rules files"
        )
    if ctx.mcp_servers:
        names = ", ".join(s.name for s in ctx.mcp_servers)
        print(f"  MCP:        {names} ({len(ctx.mcp_servers)} servers)")
    if ctx.claude_auto_memory:
        print(f"  Auto-memory: {len(ctx.claude_auto_memory)} items from past Claude Code sessions")
    tools = [k for k, v in ctx.available_tools.items() if v]
    if tools:
        print(f"  CLIs:       {', '.join(tools)}")

    print(
        f"\n  Created: {FORGE_DIR}/forge.db ({'empty' if kb.count() == 0 else f'{kb.count()} items'}, ready to learn)"
    )
    print("  Added:   .forge/ to .gitignore")
    db.close()


def cmd_status(args):
    """Show dashboard in terminal."""
    db = _get_db()
    counts = db.table_counts()
    sessions = db.list_sessions(limit=5)
    kb = KnowledgeBase(db)

    print("\nForge Status")
    print("=" * 40)
    print(f"  Knowledge base: {counts['knowledge']} items")
    print(f"  Episodes:       {counts['episodes']}")
    print(f"  Procedures:     {counts['procedures']}")
    print(f"  Research cache: {counts['research']}")
    print(f"  Sessions:       {counts['sessions']}")

    if sessions:
        print("\nRecent sessions:")
        for s in sessions[:5]:
            obj = s.get("objective", "")[:50]
            cost = s.get("total_cost", 0)
            print(f"  {s['id']}: {obj} (${cost:.2f})")
    db.close()


def cmd_doctor(args):
    """Check Claude Code, Ollama, git, MCP, models, optional features."""
    import shutil
    import sys

    issues: list[str] = []  # accumulated; printed at the end with summary

    print("\nForge Doctor")
    print("=" * 50)

    # ---- Python version (Forge requires 3.10+) ----
    py_major, py_minor = sys.version_info[:2]
    py_ok = (py_major, py_minor) >= (3, 10)
    py_status = f"{py_major}.{py_minor}.{sys.version_info[2]}"
    marker = "OK" if py_ok else "TOO OLD (need 3.10+)"
    print(f"  Python:      {py_status} {marker}")
    if not py_ok:
        issues.append(f"Python {py_status} below floor 3.10")

    # ---- Git ----
    git = shutil.which("git")
    print(f"  Git:         {'OK' if git else 'NOT FOUND'}")
    if not git:
        issues.append("git not found on PATH")

    # ---- Claude Code (optional but recommended) ----
    claude = shutil.which("claude")
    print(f"  Claude Code: {'OK' if claude else 'not installed (open-weight only mode OK)'}")

    # ---- Ollama (primary local backend) ----
    ollama = shutil.which("ollama")
    print(f"  Ollama:      {'OK' if ollama else 'NOT FOUND'}")
    if not ollama:
        issues.append("Ollama not found — recommended for open-weight models")

    # ---- OPENAI_BASE_URL (alternative local backend) ----
    openai_base = os.environ.get("OPENAI_BASE_URL", "")
    if openai_base:
        print(f"  OPENAI_BASE_URL: {openai_base}")

    # ---- .claude/ (the user's project config) ----
    has_claude_dir = os.path.exists(".claude")
    print(
        f"  .claude/:    {'Found' if has_claude_dir else 'Not found (cwd is not a Claude Code project)'}"
    )

    # ---- .forge/ (Forge state) ----
    has_forge = os.path.exists(FORGE_DIR)
    print(f"  .forge/:     {'Found' if has_forge else 'Not initialized (run forge init)'}")

    # ---- MCP servers ----
    if has_claude_dir:
        from .scanner.claude_code import read_mcp_config

        servers = read_mcp_config(".")
        if servers:
            print(f"  MCP:         {len(servers)} servers ({', '.join(s.name for s in servers)})")
        else:
            print("  MCP:         No servers configured")

    # ---- Recommended models pulled? (skip if Ollama isn't installed) ----
    if ollama:
        from .config import (
            LOCAL_CODE_MODEL,
            LOCAL_MID_MODEL,
            LOCAL_PLAN_MODEL,
            LOCAL_PREMIUM_MODEL,
        )

        recommended = {
            "planner": LOCAL_PLAN_MODEL,
            "cheap-tier generator": LOCAL_CODE_MODEL,
            "medium-tier generator": LOCAL_MID_MODEL,
            "premium-tier generator": LOCAL_PREMIUM_MODEL,
        }
        try:
            import subprocess

            # `ollama list` produces tab-separated output: NAME, ID, SIZE, MODIFIED
            result = subprocess.run(
                ["ollama", "list"], capture_output=True, text=True, timeout=10, check=False
            )
            installed = set()
            for line in result.stdout.splitlines()[1:]:  # skip header
                parts = line.split()
                if parts:
                    installed.add(parts[0].split(":")[0])  # base name w/o tag

            print("\n  Models (recommended for ADR-003 default lineup):")
            for role, model in recommended.items():
                base = model.split(":")[0]
                marker = "OK" if base in installed else "missing"
                print(f"    {role:25s} {model:30s} {marker}")
                if base not in installed:
                    issues.append(f"recommended model {model} not pulled (ollama pull {model})")
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            print(f"  Models:      could not list ({e})")

    # ---- Optional features ----
    print("\n  Optional features:")

    # sqlite-vec (vector recall on episodic store)
    try:
        from .memory.embeddings import has_sqlite_vec, is_enabled

        print(
            f"    sqlite-vec installed:    {'yes' if has_sqlite_vec() else 'no (pip install sqlite-vec)'}"
        )
        print(
            f"    FORGE_VECTOR_EPISODES:   {'enabled' if is_enabled() else 'disabled (set =1 to enable)'}"
        )
    except ImportError:
        print("    sqlite-vec:              error importing helper")

    # BAML (tolerant JSON parsing)
    try:
        from .parsing import has_baml

        print(
            f"    BAML (tolerant parser):  {'installed' if has_baml() else 'not installed (forge[robust])'}"
        )
    except ImportError:
        pass

    # ---- Summary ----
    print()
    if issues:
        print(f"  ⚠ {len(issues)} issue(s):")
        for i in issues:
            print(f"    - {i}")
        return 1
    print("  ✓ All systems go.")
    return 0


def cmd_memory(args):
    """Show KB summary or search."""
    db = _get_db()
    kb = KnowledgeBase(db)

    if args.action == "search":
        results = kb.search(query=args.query)
        if results:
            for item in results:
                print(f"  [{item['category']}] ({item['topic']}) {item['content']}")
                print(f"    confidence: {item['confidence']:.2f}, applied: {item['times_applied']}")
        else:
            print("  No results found.")

    elif args.action == "add":
        if len(args.rest) >= 3:
            kid = kb.add(args.rest[0], args.rest[1], " ".join(args.rest[2:]), "user", 0.8)
            print(f"  Added knowledge item #{kid}")
        else:
            print("  Usage: forge memory add <category> <topic> <content>")

    elif args.action == "import":
        count = kb.import_from_claude_memory(os.getcwd())
        print(f"  Imported {count} items from Claude Code auto-memory")

    else:
        all_items = kb.get_all()
        print(f"\nKnowledge Base: {len(all_items)} items")
        print("=" * 40)
        for item in all_items[:20]:
            print(f"  [{item['category']}] ({item['topic']}) {item['content']}")
        if len(all_items) > 20:
            print(f"  ... and {len(all_items) - 20} more")

    db.close()


def cmd_budget(args):
    """Show spend vs cap."""
    db = _get_db()
    sessions = db.list_sessions(limit=1)
    if sessions:
        cost = sessions[0].get("total_cost", 0)
        print(f"\nLast session cost: ${cost:.4f}")
    total = sum(s.get("total_cost", 0) for s in db.list_sessions(limit=100))
    print(f"Total spend: ${total:.4f}")
    db.close()


def _sprint_from_row(row: dict):
    """Reconstruct a SprintContract from a DB row dict (JSON list fields may be
    stored as strings)."""
    import json

    from .models import SprintContract

    def _list(v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (ValueError, TypeError):
                return []
        return v or []

    return SprintContract(
        id=row.get("id", ""),
        session_id=row.get("session_id", ""),
        description=row.get("description", ""),
        done_criteria=_list(row.get("done_criteria")),
        depends_on=_list(row.get("depends_on")),
        files_scope=_list(row.get("files_scope")),
        assigned_model=row.get("assigned_model") or "",
        status=row.get("status", "pending"),
        estimated_tokens=row.get("estimated_tokens", 0) or 0,
    )


def cmd_add(args):
    """Add a single task as a pending sprint (skips the planner)."""
    from .config import LOCAL_CODE_MODEL
    from .models import SprintContract

    db = _get_db()
    sprint = SprintContract(
        session_id="cli-adhoc",
        description=args.description,
        done_criteria=["Task completed as described"],
        assigned_model=getattr(args, "model", None) or LOCAL_CODE_MODEL,
        status="pending",
    )
    db.save_sprint(sprint)
    print(f"Added pending sprint {sprint.id}: {sprint.description}")
    print("Run it with:  forge run")
    db.close()
    return 0


def cmd_plan(args):
    """Decompose an objective into pending sprints (persisted for `forge run`)."""
    from .agents import planner
    from .memory.retriever import Retriever
    from .models import Session

    db = _get_db()
    ctx = _run_async(scan_project("."))
    session = Session(project_path=ctx.path, objective=args.objective)
    db.save_session(session)
    kb_context = Retriever(db).get_context_for_task(args.objective)
    sprints = _run_async(planner.plan(args.objective, ctx, session.id, kb_context))
    for s in sprints:
        db.save_sprint(s)
    print(f"\nPlan: {len(sprints)} sprint(s) for: {args.objective}")
    for s in sprints:
        crit = " [critical]" if getattr(s, "critical", False) else ""
        print(f"  [{s.id}] {s.description} ({s.assigned_model}){crit}")
        for c in s.done_criteria:
            print(f"        - {c}")
    print("\nRun them with:  forge run")
    db.close()
    return 0


def cmd_run(args):
    """Execute pending sprints (all, or one by id) through the harness."""
    from . import scheduler
    from .budget import BudgetController
    from .memory.episodic import EpisodicStore
    from .memory.retriever import Retriever

    db = _get_db()
    ctx = _run_async(scan_project("."))
    sprint_id = getattr(args, "sprint_id", None)

    pending = []
    for sess in db.list_sessions(limit=10):
        for row in db.get_sprints_for_session(sess["id"]):
            if row.get("status") == "pending" and (not sprint_id or row.get("id") == sprint_id):
                pending.append(row)
    # Ad-hoc sprints from `forge add` live under a synthetic session id.
    for row in db.get_sprints_for_session("cli-adhoc"):
        if row.get("status") == "pending" and (not sprint_id or row.get("id") == sprint_id):
            pending.append(row)

    if not pending:
        print('No pending sprints. Create some with `forge plan "..."` or `forge add "..."`.')
        db.close()
        return 1

    budget = BudgetController()
    retriever = Retriever(db)
    episodic = EpisodicStore(db)

    completed = 0
    for row in pending:
        sprint = _sprint_from_row(row)
        print(f"\n→ {sprint.id}: {sprint.description}")
        result = _run_async(
            scheduler.execute_sprint(
                sprint, ctx, sprint.session_id or "cli-run", db, budget, retriever, episodic
            )
        )
        status = getattr(result, "status", "unknown")
        print(f"  {status}")
        if status == "completed":
            completed += 1
    print(f"\n{completed}/{len(pending)} sprint(s) completed.")
    db.close()
    return 0 if completed == len(pending) else 1


def cmd_review(args):
    """Run the multi-perspective review panel on a sprint's worktree diff."""
    from . import worktree
    from .agents import reviewer

    db = _get_db()
    row = db.get_sprint(args.sprint_id)
    if not row:
        print(f"No sprint {args.sprint_id}")
        db.close()
        return 1
    try:
        diff = _run_async(worktree.get_diff(args.sprint_id))
    except Exception as e:
        print(f"Could not read worktree diff: {e}")
        db.close()
        return 1
    if not diff.strip():
        print("Empty diff — nothing to review.")
        db.close()
        return 1
    result = _run_async(reviewer.review(diff))
    print(f"\nReview verdict: {result.overall_verdict}")
    for p in result.perspectives:
        print(f"  [{p.name}] {p.verdict}")
    if result.critical_issues:
        print("\nCritical issues:")
        for issue in result.critical_issues:
            print(f"  - {issue}")
    db.close()
    return 0


def cmd_merge(args):
    """Show or approve worktree merges (the merge gate, from the terminal)."""
    from . import worktree

    worktrees = _run_async(worktree.list_worktrees())
    # The main checkout shows up too; only sprint worktrees live under .forge.
    sprint_wts = [w for w in worktrees if ".forge" in (w.get("path") or "")]

    if not sprint_wts:
        print("No sprint worktrees to merge.")
        return 0

    if getattr(args, "show", False) or not getattr(args, "approve", False):
        print("\nPending worktrees:")
        for w in sprint_wts:
            branch = w.get("branch", "(detached)")
            print(f"  {w['path']}  {branch}")
        print("\nApprove with:  forge merge --approve")
        return 0

    # --approve: merge each sprint branch into the current branch.
    merged = 0
    for w in sprint_wts:
        branch = (w.get("branch") or "").replace("refs/heads/", "")
        if not branch:
            continue
        code, _out, err = _run_async(worktree._run_git(["merge", "--no-ff", branch]))
        if code == 0:
            print(f"  ✓ merged {branch}")
            merged += 1
        else:
            print(f"  ✗ conflict merging {branch}: {err.strip()[:120]}")
    print(f"\n{merged}/{len(sprint_wts)} merged.")
    return 0


def cmd_doc(args):
    """Generate a document locally from a brief and save it under .forge/artifacts/."""
    from .agents import document

    result = _run_async(document.write_document(args.brief))
    if not result.success:
        print(f"Document generation failed: {result.error}")
        return 1
    name = getattr(args, "name", None) or "document"
    fmt = getattr(args, "format", None) or "md"
    path = document.save_document(result, name=name, fmt=fmt)
    print(f"\nWrote {path} ({len(result.content)} chars, model {result.model})")
    return 0


def cmd_digest(args):
    """Map-reduce a large file into a concise digest (saved as an artifact)."""
    from . import artifacts, chunker, filefetch

    fetched = filefetch.read_file_text(args.path, max_bytes=5_000_000)
    if not fetched.get("ok"):
        print(f"Cannot read {args.path}: {fetched.get('error')}")
        return 1
    text = fetched["content"]
    print(f"Digesting {args.path} ({len(text)} chars) with the local model…")
    digest = _run_async(
        chunker.ollama_digest(text, target_tokens=int(getattr(args, "tokens", 800)))
    )
    if not digest.strip():
        print("Digest came back empty (is Ollama running?).")
        return 1
    name = Path(args.path).stem + "-digest"
    path = artifacts.save_artifact(name, digest, fmt="md")
    print(f"\nWrote {path} ({len(digest)} chars)")
    return 0


def cmd_bench(args):
    """Run (or plan) the SWE-bench kill gate at a selected metric profile.

    The ``--profile`` selects how deep/expensive the run is (the same set the
    UI dropdown offers): gate → diagnostic → baseline (2×) → full (N×). A live
    run needs Docker + GPU + pulled models; ``--list-profiles`` and ``--dry-run``
    work offline so users can inspect the plan and pick a profile first.
    """
    from eval.swebench import adapter, tiers
    from eval.swebench.metrics import KILL_THRESHOLD_PCT

    if getattr(args, "list_profiles", False):
        print("\nBench profiles (pick with --profile):\n")
        for spec in tiers.all_profiles():
            tier_names = ", ".join(t.name for t in spec.tiers)
            print(f"  {spec.profile.value:<11} {spec.label}  (~{spec.cost_multiplier()}× runs)")
            print(f"              tiers: {tier_names}")
            print(f"              {spec.description}\n")
        return 0

    try:
        spec = tiers.get_profile(getattr(args, "profile", "gate"))
    except ValueError as e:
        print(e)
        return 1

    subset_path = getattr(args, "subset", None)
    tasks = adapter.load_tasks_from_jsonl(subset_path) if subset_path else []

    print(f"\nProfile: {spec.label} ({spec.profile.value})")
    print(f"  tiers computed:   {', '.join(t.name for t in spec.tiers)}")
    print(
        f"  runs over subset: {spec.runs}"
        + (" + single-agent baseline" if spec.needs_baseline_run else "")
    )
    print(f"  cost multiplier:  ~{spec.cost_multiplier()}× a single gate run")
    print(
        f"  subset:           {subset_path or '(none given — use --subset)'} ({len(tasks)} tasks)"
    )
    print(f"  kill criterion:   ≥{KILL_THRESHOLD_PCT:.0f}% resolved (ADR-015)")

    if getattr(args, "dry_run", False) or not tasks:
        if not tasks and not getattr(args, "dry_run", False):
            print(
                "\nNo tasks loaded — pass --subset PATH (see eval/swebench/README.md), "
                "or use --dry-run to preview the plan."
            )
        else:
            print("\n(dry run — nothing executed)")
        return 0

    # Live run: needs Docker/GPU/models. real_forge_runner is a stub until the
    # hardware-bound Stage 3 is wired; surface that honestly rather than crash.
    try:
        result = adapter.run_subset(tasks, forge_runner=adapter.real_forge_runner)
    except NotImplementedError as e:
        print(f"\nLive run unavailable: {e}")
        print("See eval/swebench/README.md to wire the Docker harness on capable hardware.")
        return 2
    print("\n" + result.summary())
    return 0


def cmd_models(args):
    """List / pull the default local model lineup with a disk-safety guard."""
    from . import model_setup

    action = getattr(args, "action", "list") or "list"
    models = model_setup.DEFAULT_MODEL_SET
    present = _ollama_present_models()

    if action == "list":
        print("\nDefault local model lineup:")
        for m in models:
            mark = "✓ present" if m.name in present else "· not pulled"
            print(f"  {m.name:<28} ~{m.size_gb:>5.1f} GB   {mark}")
        free = model_setup.free_disk_gb(".")
        print(f"\nFree disk: {free:.1f} GB")
        return 0

    if action == "pull":
        free = model_setup.free_disk_gb(".")
        plan = model_setup.plan_pull(models, free_gb=free, present=present)
        print(f"\nPlan: pull {len(plan.to_pull)} model(s), ~{plan.total_gb:.1f} GB")
        for m in plan.to_pull:
            print(f"  + {m.name}  (~{m.size_gb:.1f} GB)")
        print(f"Free disk: {plan.free_gb:.1f} GB  (headroom {plan.headroom_gb:.1f} GB)")
        if not plan.ok:
            print(f"\n✗ Refused: {plan.refused_reason}")
            return 1
        if getattr(args, "dry_run", False):
            print("\n(dry run — nothing pulled)")
            return 0
        for m in plan.to_pull:
            print(f"\n→ ollama pull {m.name}")
            rc = _ollama_pull(m.name)
            if rc != 0:
                print(f"✗ pull failed for {m.name} (exit {rc})")
                return rc
        print("\n✓ models ready")
        return 0

    print(f"Unknown models action: {action}")
    return 1


def _ollama_present_models() -> set[str]:
    """Names of locally-installed Ollama models (empty set if Ollama absent)."""
    import shutil
    import subprocess

    if not shutil.which("ollama"):
        return set()
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    names: set[str] = set()
    for line in out.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            # ``ollama list`` shows "name:tag"; record both the full and base name.
            names.add(parts[0])
            names.add(parts[0].split(":")[0])
    return names


def _ollama_pull(name: str) -> int:
    import subprocess

    try:
        return subprocess.run(["ollama", "pull", name], check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def cmd_serve(args):
    """Start daemon + open browser dashboard.

    Task 1.7: SIGTERM/SIGINT now flips a shutdown_event that ``start_server``
    awaits, so the WebSocket layer closes existing client connections with
    code 1001 (going away), waits for in-flight handlers, and only then
    returns. ``db.close()`` runs in the surrounding finally so WAL flushes
    cleanly even on Kubernetes evict / explicit ``kill <pid>``.

    First-run wizard: if ``.forge/connectors.toml`` does not yet have a
    ``meta.wizard_completed_at`` stamp, we auto-launch the connector
    wizard before starting the WS server. Skipped in non-tty mode (CI).
    """
    import signal
    import time

    from .config import WS_HOST
    from .worktree import register_signal_handlers
    from .ws_server import start_server

    # Stale-daemon guard: a previous `forge serve` that didn't shut down cleanly
    # leaves port 9111 bound. Detect it and either reclaim (--force) or print a
    # clean, actionable message — never a raw bind traceback.
    if _port_in_use(WS_HOST, WS_PORT):
        pid = _pid_on_port(WS_PORT)
        if getattr(args, "force", False) and pid:
            print(f"Reclaiming port {WS_PORT} from pid {pid} (--force)…")
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
                time.sleep(1.0)
                if _port_in_use(WS_HOST, WS_PORT):
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(0.5)
        else:
            print(f"\n✗ Port {WS_PORT} is already in use" + (f" (pid {pid})" if pid else "") + ".")
            print("  Another `forge serve` is probably still running.")
            if pid:
                print(f"  Stop it:      kill {pid}")
            print("  Or reclaim it: forge serve --force\n")
            return 1

    # First-run wizard hook (auto-trigger). The wizard itself is a no-op
    # when stdin isn't a TTY, so this is safe under nohup / docker -d.
    forge_dir = Path(os.getcwd()) / ".forge"
    if not _has_wizard_run(forge_dir):
        _maybe_run_wizard(forge_dir)

    register_signal_handlers()
    db = _get_db()
    budget = BudgetController()

    # Launch the dashboard alongside the daemon so `forge serve` is one command
    # (unless --no-ui for headless / CI). Stopped in the finally below.
    ui_proc = None if getattr(args, "no_ui", False) else _launch_ui()

    print("\nForge daemon starting...")
    print(f"  WebSocket: ws://127.0.0.1:{WS_PORT}")
    if ui_proc is not None:
        print("  Dashboard: http://localhost:3000")
    print("  Press Ctrl+C for graceful shutdown\n")

    async def _serve():
        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        # Schedule shutdown_event.set() on SIGTERM/SIGINT. add_signal_handler
        # is the asyncio-native path; we fall back to signal.signal on
        # Windows where add_signal_handler raises NotImplementedError.
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, shutdown_event.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: shutdown_event.set())

        try:
            await start_server(db, budget, shutdown_event=shutdown_event)
        finally:
            db.close()

    try:
        _run_async(_serve())
    finally:
        _stop_ui(ui_proc)


def cmd_reset(args):
    """Clear tasks (keep KB and patterns)."""
    db = _get_db()
    with db._conn:
        db._conn.execute("DELETE FROM episodes")
        db._conn.execute("DELETE FROM sprint_contracts")
        db._conn.execute("DELETE FROM sessions")
    print("  Cleared tasks and sessions. Knowledge base preserved.")
    db.close()


def cmd_tui(args):
    """Launch the terminal UI — Sprint 6.5.

    Same WebSocket interface as ``forge serve``'s dashboard; both can
    run simultaneously. The TUI is the Claude-Code/Codex-style terminal
    surface — works over SSH, no browser required.

    Requires the optional ``[tui]`` extra (textual + rich). The
    daemon-side ``forge serve`` does NOT need it; only this command does.
    """
    from .tui import run_tui

    return run_tui()


def cmd_wizard(args):
    """Launch the first-run connector setup wizard.

    Idempotent — safe to re-run. Picks up where it left off; never
    overwrites credentials. See daemon/wizard.py for the full flow.
    """
    from pathlib import Path

    from .wizard import WizardOptions, run_wizard

    project_path = Path(os.getcwd())
    forge_dir = project_path / ".forge"
    forge_dir.mkdir(exist_ok=True)
    claude_settings = project_path / ".claude" / "settings.json"

    opts = WizardOptions(
        project_path=project_path,
        forge_dir=forge_dir,
        claude_settings_path=claude_settings,
        non_interactive=getattr(args, "yes", False),
    )
    run_wizard(opts)
    return 0


# ──────────────────────────────────────────────────────────────────────
#  First-run hook helpers (used by cmd_serve)
# ──────────────────────────────────────────────────────────────────────


def _has_wizard_run(forge_dir) -> bool:
    """Cheap check used in cmd_serve to decide whether to auto-trigger."""
    from .wizard import has_completed_wizard

    return has_completed_wizard(forge_dir)


def _maybe_run_wizard(forge_dir) -> None:
    """Launch the wizard from cmd_serve if conditions are right.

    Skips silently in non-tty environments (CI, docker -d, nohup) so
    background-launched daemons don't block on stdin.
    """
    import os as _os
    import sys

    if not sys.stdin.isatty():
        return
    print("\n  No connectors configured yet — launching the setup wizard.")
    print("  (Skip with: forge serve --skip-wizard, or re-run later: forge wizard)")
    print()
    args_obj = type("A", (), {"yes": False})
    cmd_wizard(args_obj)
    # Re-confirm before continuing — user may want to set env vars first.
    if _os.isatty(0):
        try:
            input("  Press Enter to start the daemon, Ctrl-C to exit and set env vars first: ")
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)


def cmd_connectors(args):
    """Connector management — list / add / enable / disable / test / remove.

    Sprint 6.1.6: ``forge connectors test <name>`` runs a healthcheck
    invocation through the dispatcher so the user can verify a plugin
    is correctly installed, pinned, and able to spawn under the sandbox
    runtime before relying on it in a sprint.

    The CLI surface is intentionally narrow for v0.1.0; richer ops
    (update, audit, edit-capabilities) land in Sprint 6.4 alongside
    the reference connectors.
    """
    return _run_async(_cmd_plugin("connector", args))


def cmd_skills(args):
    """Skill management — install / list / enable / disable / test / remove."""
    return _run_async(_cmd_plugin("skill", args))


async def _cmd_plugin(kind: str, args) -> int:
    """Shared implementation for ``forge connectors`` and ``forge skills``.

    Both surfaces share the same lifecycle (load → pin → test → run); the
    only difference is which registry / loader to use. We dispatch on
    ``kind`` rather than duplicating the subcommand bodies.
    """
    from pathlib import Path as _Path

    from .connectors.registry import load_connector
    from .scheduler import dispatch_plugin
    from .skills import PluginsLock, default_lock_path
    from .skills.registry import load_skill

    project_path = _Path(os.getcwd())
    forge_dir = project_path / ".forge"
    lock = PluginsLock(default_lock_path(project_path))

    action = args.action
    name = getattr(args, "name", None) or ""

    if action == "list":
        # List pinned plugins of this kind.
        for key, entry in sorted(lock.all_entries().items()):
            if not key.startswith(f"{kind}:"):
                continue
            plugin_name = key.split(":", 1)[1]
            print(f"  {plugin_name:20s}  v{entry.version or '?':10s}  {entry.sha256[:12]}…")
        return 0

    if action == "add" or action == "install":
        path_arg = getattr(args, "path", None) or name
        if not path_arg:
            print(f"  Usage: forge {kind}s {action} <path>")
            return 1
        plugin_dir = _Path(path_arg).expanduser().resolve()
        try:
            entry = load_skill(plugin_dir) if kind == "skill" else load_connector(plugin_dir)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ✗ failed to load plugin: {e}")
            return 1

        manifest_name = entry.manifest.name
        # If the plugin is already pinned with different capabilities,
        # require re-approval (Sprint 6.1.5 hookup).
        from .skills.dispatch import _build_capabilities_dict
        from .wizard import confirm_capability_changes

        new_caps = _build_capabilities_dict(entry.manifest)
        diff = lock.diff_capabilities(kind, manifest_name, new_caps)
        if diff is not None:
            approved = confirm_capability_changes(
                plugin_kind=kind,
                plugin_name=manifest_name,
                diff=diff,
            )
            if not approved:
                print(f"  ✗ {kind} {manifest_name} not approved — leaving previous pin intact")
                return 1

        lock.pin(
            kind,
            manifest_name,
            sha256=entry.manifest_sha256,
            version=entry.manifest.version,
            approved_capabilities=new_caps,
        )
        forge_dir.mkdir(exist_ok=True)
        lock.save()
        print(f"  ✓ pinned {kind}:{manifest_name} v{entry.manifest.version}")
        print(f"    sha256: {entry.manifest_sha256[:16]}…")
        return 0

    if action == "remove":
        if not name:
            print(f"  Usage: forge {kind}s remove <name>")
            return 1
        if lock.unpin(kind, name):
            forge_dir.mkdir(exist_ok=True)
            lock.save()
            print(f"  ✓ unpinned {kind}:{name}")
            return 0
        print(f"  ✗ no pinned {kind}:{name}")
        return 1

    if action == "test":
        if not name:
            print(f"  Usage: forge {kind}s test <name>")
            return 1
        # Look up the pinned entry — we need its plugin_path stored
        # nowhere yet. For v0.1.0 the convention is plugins live at
        # ~/.forge/plugins/<name> (connectors) or ~/.forge/skills/<name>
        # (skills). The user can override by passing --path.
        if kind == "skill":
            default_root = _Path.home() / ".forge" / "skills"
        else:
            default_root = _Path.home() / ".forge" / "plugins"
        path_arg = getattr(args, "path", None)
        plugin_dir = _Path(path_arg).expanduser().resolve() if path_arg else (default_root / name)
        if not plugin_dir.is_dir():
            print(f"  ✗ no plugin directory at {plugin_dir}")
            print("    Use --path to point at the plugin source if it lives elsewhere.")
            return 1

        try:
            entry = load_skill(plugin_dir) if kind == "skill" else load_connector(plugin_dir)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ✗ failed to load plugin: {e}")
            return 1

        # Run a healthcheck through the dispatcher. The plugin's
        # entry_script doubles as healthcheck unless a separate
        # scripts/healthcheck.py exists.
        from .db import ForgeDB

        db = ForgeDB(DB_PATH)
        try:
            result = await dispatch_plugin(
                kind=kind,
                name=entry.manifest.name,
                plugin_path=plugin_dir,
                manifest=entry.manifest,
                manifest_sha256=entry.manifest_sha256,
                args=[],
                db=db,
                lock=lock,
            )
        finally:
            db.close()

        if result.ok:
            print(f"  ✓ {kind}:{entry.manifest.name} healthcheck passed")
            if result.sandbox_result and result.sandbox_result.duration_seconds:
                print(f"    duration: {result.sandbox_result.duration_seconds:.2f}s")
            return 0

        print(f"  ✗ {kind}:{entry.manifest.name} healthcheck FAILED")
        if result.error:
            print(f"    error: {result.error}")
        if result.sandbox_result and result.sandbox_result.stderr:
            stderr_tail = result.sandbox_result.stderr.strip().splitlines()[-5:]
            for line in stderr_tail:
                print(f"    | {line}")
        return 1

    print(f"  Unknown action: {action}")
    return 1


def cmd_replay(args):
    """Replay a session's trace JSONL.

    Usage:
        forge replay                    # list available sessions
        forge replay <session_id>       # pretty-print events to stdout
        forge replay <session_id> --raw # emit raw JSONL (pipeable to jq)
    """
    from . import replay

    if not args.session_id:
        sessions = replay.list_sessions()
        if not sessions:
            print("No sessions with trace files found in .forge/sessions/.")
            return 0
        print("Available sessions (newest first):")
        for sid in sessions:
            print(f"  {sid}")
        print("\nUsage: forge replay <session_id>")
        return 0

    rc = replay.replay_to_stdout(args.session_id, pretty=not args.raw)
    return 0 if rc > 0 else 1


def cmd_mcp_serve(args):
    """Run Forge's KB-as-MCP server over stdio.

    Register in any Claude Code / Cursor / Continue / Goose `.claude/settings.json`
    so that MCP-aware agents can query Forge's accumulated KB:

        "mcpServers": {
            "forge-kb": {
                "command": "forge",
                "args": ["mcp-serve"]
            }
        }

    See daemon/mcp_server.py for the exposed tool / resource / prompt set.
    """
    from . import mcp_server

    return mcp_server.main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge", description="Forge multi-agent orchestrator")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize Forge in current project")
    sub.add_parser("status", help="Show status dashboard")
    sub.add_parser("doctor", help="Check dependencies")
    sub.add_parser("budget", help="Show budget")
    srv = sub.add_parser("serve", help="Start daemon + dashboard (one command)")
    srv.add_argument("--no-ui", action="store_true", help="Run the daemon only (headless / CI)")
    srv.add_argument(
        "--force",
        action="store_true",
        help="Reclaim the port if a stale daemon is still bound to it",
    )
    sub.add_parser(
        "tui",
        help="Launch the Textual terminal UI (Codex/Claude-Code-style; needs forge[tui] extra)",
    )
    sub.add_parser("reset", help="Clear tasks (keep KB)")

    pl = sub.add_parser("plan", help="Decompose an objective into pending sprints")
    pl.add_argument("objective", help="What to build")

    rn = sub.add_parser("run", help="Execute pending sprints (all, or one by id)")
    rn.add_argument("sprint_id", nargs="?", default=None, help="Run only this sprint")

    ad = sub.add_parser("add", help="Add a single task as a pending sprint (skip planner)")
    ad.add_argument("description", help="The task to do")
    ad.add_argument("--model", default=None, help="Override the assigned model")

    rv = sub.add_parser("review", help="Run the multi-perspective review panel on a sprint")
    rv.add_argument("sprint_id", help="Sprint whose worktree diff to review")

    mg = sub.add_parser("merge", help="Show or approve worktree merges (the merge gate)")
    mg.add_argument("--show", action="store_true", help="List pending worktrees (default)")
    mg.add_argument("--approve", action="store_true", help="Merge sprint branches into HEAD")

    dc = sub.add_parser("doc", help="Generate a document locally from a brief")
    dc.add_argument("brief", help="What the document should cover")
    dc.add_argument("--name", default="document", help="Artifact file name")
    dc.add_argument(
        "--format", default="md", choices=["md", "txt", "html", "docx"], help="Export format"
    )

    dg = sub.add_parser("digest", help="Map-reduce a large file into a concise digest")
    dg.add_argument("path", help="File to digest")
    dg.add_argument("--tokens", default=800, type=int, help="Target digest size (tokens)")

    bench = sub.add_parser(
        "bench", help="Run (or plan) the SWE-bench kill gate at a metric profile"
    )
    bench.add_argument(
        "--profile",
        choices=["gate", "diagnostic", "baseline", "full"],
        default="gate",
        help="Metric depth: gate (1×) → diagnostic (1×) → baseline (2×) → full (N×)",
    )
    bench.add_argument("--subset", default=None, help="Path to a SWE-bench tasks JSONL")
    bench.add_argument(
        "--list-profiles", action="store_true", help="List profiles + their tiers/cost and exit"
    )
    bench.add_argument(
        "--dry-run", action="store_true", help="Print the run plan without executing"
    )

    mdl = sub.add_parser("models", help="List / pull the default local model lineup")
    mdl.add_argument("action", nargs="?", default="list", choices=["list", "pull"])
    mdl.add_argument(
        "--dry-run", action="store_true", help="Show the pull plan without downloading"
    )
    wiz = sub.add_parser(
        "wizard",
        help="Run the first-run connector setup wizard (idempotent; safe to re-run)",
    )
    wiz.add_argument("--yes", action="store_true", help="Non-interactive mode (CI / Docker)")
    sub.add_parser(
        "mcp-serve",
        help="Run Forge KB as an MCP server over stdio (for Claude Desktop / Cursor / Continue)",
    )

    mem = sub.add_parser("memory", help="Knowledge base operations")
    mem.add_argument(
        "action", nargs="?", default="list", choices=["list", "search", "add", "import"]
    )
    mem.add_argument("query", nargs="?", default="")
    mem.add_argument("rest", nargs="*")

    rep = sub.add_parser("replay", help="Replay a session's trace JSONL audit log")
    rep.add_argument(
        "session_id",
        nargs="?",
        default=None,
        help="Session to replay; omit to list available sessions",
    )
    rep.add_argument(
        "--raw",
        action="store_true",
        help="Emit raw JSONL instead of pretty-printed (pipeable to jq)",
    )

    # ---- connectors / skills (Sprint 6.1.6) ----
    #
    # Both share the same lifecycle (load → pin → test → remove); the only
    # difference is which loader to use. We define the parser shape once
    # and add it under both subcommands so muscle memory works either way.
    for surface, help_blurb in (
        ("connectors", "Manage native connectors (load / pin / test / remove)"),
        ("skills", "Manage Claude-Code-compatible skills (load / pin / test / remove)"),
    ):
        s = sub.add_parser(surface, help=help_blurb)
        s.add_argument(
            "action",
            choices=["list", "add", "install", "test", "remove"],
            help=(
                "list: show pinned plugins; "
                "add/install: load a plugin dir + pin it in plugins.lock; "
                "test: run a healthcheck through the sandbox dispatcher; "
                "remove: unpin (does not delete files on disk)"
            ),
        )
        s.add_argument("name", nargs="?", default="", help="Plugin name (or path for add/install)")
        s.add_argument(
            "--path",
            default=None,
            help="Path to the plugin directory (overrides the default ~/.forge lookup)",
        )

    return parser


def main():
    # Use the dedicated logging helper so the RedactionFilter (ADR-017)
    # is applied to both stderr and the rotating file handler.
    from .log import setup_logging

    setup_logging()
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "doctor": cmd_doctor,
        "memory": cmd_memory,
        "budget": cmd_budget,
        "models": cmd_models,
        "bench": cmd_bench,
        "plan": cmd_plan,
        "run": cmd_run,
        "add": cmd_add,
        "review": cmd_review,
        "merge": cmd_merge,
        "doc": cmd_doc,
        "digest": cmd_digest,
        "serve": cmd_serve,
        "tui": cmd_tui,
        "reset": cmd_reset,
        "replay": cmd_replay,
        "mcp-serve": cmd_mcp_serve,
        "wizard": cmd_wizard,
        "connectors": cmd_connectors,
        "skills": cmd_skills,
    }

    if args.command in commands:
        rc = commands[args.command](args)
        return rc if isinstance(rc, int) else 0
    parser.print_help()
    return 1

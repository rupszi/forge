"""CLI commands for forge."""

import argparse
import asyncio
import os

from .budget import BudgetController
from .config import DB_PATH, FORGE_DIR, WS_PORT
from .db import ForgeDB
from .memory.knowledge import KnowledgeBase
from .scanner.project import scan_project


def _get_db() -> ForgeDB:
    return ForgeDB(DB_PATH)


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
    from pathlib import Path

    from .worktree import register_signal_handlers
    from .ws_server import start_server

    # First-run wizard hook (auto-trigger). The wizard itself is a no-op
    # when stdin isn't a TTY, so this is safe under nohup / docker -d.
    forge_dir = Path(os.getcwd()) / ".forge"
    if not _has_wizard_run(forge_dir):
        _maybe_run_wizard(forge_dir)

    register_signal_handlers()
    db = _get_db()
    budget = BudgetController()

    print("\nForge daemon starting...")
    print(f"  WebSocket: ws://127.0.0.1:{WS_PORT}")
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

    _run_async(_serve())


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
    sub.add_parser("serve", help="Start daemon + dashboard")
    sub.add_parser(
        "tui",
        help="Launch the Textual terminal UI (Codex/Claude-Code-style; needs forge[tui] extra)",
    )
    sub.add_parser("reset", help="Clear tasks (keep KB)")
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
        "serve": cmd_serve,
        "tui": cmd_tui,
        "reset": cmd_reset,
        "replay": cmd_replay,
        "mcp-serve": cmd_mcp_serve,
        "wizard": cmd_wizard,
    }

    if args.command in commands:
        rc = commands[args.command](args)
        return rc if isinstance(rc, int) else 0
    parser.print_help()
    return 1

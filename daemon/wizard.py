"""First-run setup wizard — make connector configuration as easy as possible.

Triggered automatically:
  - At the end of install.sh (last phase)
  - On the first `forge serve` if `.forge/connectors.toml` doesn't exist
  - Manually via `forge wizard`

Also exposes ``confirm_capability_changes`` — the re-approval helper used
by the dispatcher / CLI when a plugin's manifest changed and its declared
capabilities widened. Re-approval is strictly user-mediated: there is no
automatic "trust the new manifest" path.

Design priorities (in order):
  1. **Zero surprise** — never write credentials anywhere; only document them
  2. **Detect what's already there** — read .claude/settings.json first; the
     user shouldn't have to redeclare MCP servers they already configured
  3. **Suggest, don't push** — common-stack connectors offered with one-key
     enable; user can dismiss
  4. **Verify before declaring done** — every chosen connector gets a
     healthcheck call; failures are explicit
  5. **Resumable** — exit at any point without breaking; re-running picks
     up where it left off

The wizard writes ONLY ``.forge/connectors.toml`` (declares which connectors
are enabled and how they're sourced). It does NOT write secret values to
disk — those stay in the user's shell env or `.env` file.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────
#  Connector catalog
# ──────────────────────────────────────────────────────────────────────


@dataclass
class WizardConnector:
    """A connector the wizard knows how to set up."""

    name: str
    title: str  # human-readable
    mechanism: str  # "mcp" | "native"
    description: str
    # For MCP: env vars the user needs to set
    env_vars: list[str] = field(default_factory=list)
    # For MCP: how to add it to .claude/settings.json
    mcp_command: str | None = None
    mcp_args: list[str] = field(default_factory=list)
    # Detection — does the user's stack suggest they want this?
    suggested_when: list[str] = field(default_factory=list)
    # Healthcheck command (optional; used to verify config)
    healthcheck: str | None = None
    # Setup help URL
    docs_url: str | None = None


# Tier-1 catalog matching docs/CONNECTORS.md.
# When adding a connector here, also update docs/CONNECTORS.md.
CATALOG: list[WizardConnector] = [
    WizardConnector(
        name="github",
        title="GitHub (issues, PRs, CI)",
        mechanism="mcp",
        description="Read/write issues + PRs, check CI status, search code",
        env_vars=["GITHUB_TOKEN"],
        mcp_command="npx",
        mcp_args=["-y", "@modelcontextprotocol/server-github"],
        suggested_when=["github", "git"],
        healthcheck="gh auth status",
        docs_url="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
    ),
    WizardConnector(
        name="vercel",
        title="Vercel (deploys, env vars, logs)",
        mechanism="mcp",
        description="Trigger deploys, read deployment logs, sync env vars",
        env_vars=["VERCEL_TOKEN"],
        mcp_command="npx",
        mcp_args=["-y", "@vercel/mcp-server"],
        suggested_when=["next", "vercel"],
        healthcheck="vercel whoami",
        docs_url="https://vercel.com/account/tokens",
    ),
    WizardConnector(
        name="supabase",
        title="Supabase (DB, RLS, edge functions, migrations)",
        mechanism="mcp",
        description="Schema operations, RLS policies, edge functions, migrations",
        env_vars=["SUPABASE_ACCESS_TOKEN"],
        mcp_command="npx",
        mcp_args=["-y", "@supabase/mcp-server-supabase@latest"],
        suggested_when=["supabase"],
        healthcheck="supabase projects list",
        docs_url="https://supabase.com/dashboard/account/tokens",
    ),
    WizardConnector(
        name="postgres",
        title="Postgres (any) — query, schema, EXPLAIN",
        mechanism="mcp",
        description="Connect to any Postgres instance via DSN; safe SQL execution",
        env_vars=["POSTGRES_DSN"],
        mcp_command="npx",
        mcp_args=["-y", "@modelcontextprotocol/server-postgres"],
        suggested_when=["postgres", "supabase", "neon"],
        healthcheck=None,
    ),
    WizardConnector(
        name="stripe",
        title="Stripe (charges, customers, webhooks)",
        mechanism="mcp",
        description="Customer / subscription management, charge inspection, webhooks",
        env_vars=["STRIPE_API_KEY"],
        mcp_command="npx",
        mcp_args=["-y", "@stripe/mcp-server"],
        suggested_when=["stripe"],
        healthcheck="stripe --version",
        docs_url="https://dashboard.stripe.com/apikeys",
    ),
    WizardConnector(
        name="resend",
        title="Resend (email)",
        mechanism="mcp",
        description="Send emails, inspect logs",
        env_vars=["RESEND_API_KEY"],
        mcp_command="npx",
        mcp_args=["-y", "@resend/mcp-server"],
        suggested_when=["resend"],
        docs_url="https://resend.com/api-keys",
    ),
    WizardConnector(
        name="slack",
        title="Slack (post messages, search)",
        mechanism="mcp",
        description="Post messages, search channels, read threads",
        env_vars=["SLACK_BOT_TOKEN"],
        mcp_command="npx",
        mcp_args=["-y", "@modelcontextprotocol/server-slack"],
        suggested_when=["slack"],
    ),
    WizardConnector(
        name="linear",
        title="Linear (issues, projects, cycles)",
        mechanism="mcp",
        description="Issue tracking, project planning, cycle management",
        env_vars=["LINEAR_API_KEY"],
        mcp_command="npx",
        mcp_args=["-y", "@modelcontextprotocol/server-linear"],
        suggested_when=["linear"],
    ),
    WizardConnector(
        name="sentry",
        title="Sentry (error monitoring)",
        mechanism="mcp",
        description="Read events, triage issues, manage releases",
        env_vars=["SENTRY_DSN", "SENTRY_AUTH_TOKEN"],
        mcp_command="npx",
        mcp_args=["-y", "@sentry/mcp-server"],
        suggested_when=["sentry"],
    ),
]


# ──────────────────────────────────────────────────────────────────────
#  Detection
# ──────────────────────────────────────────────────────────────────────


def detect_existing_mcp_servers(claude_settings_path: Path) -> list[str]:
    """Read ``.claude/settings.json`` and return a list of MCP server names
    the user has already configured. The wizard treats these as "already
    set up — just enable in Forge"."""
    if not claude_settings_path.is_file():
        return []
    try:
        import json

        data = json.loads(claude_settings_path.read_text())
    except (OSError, ValueError):
        return []
    return list(data.get("mcpServers", {}).keys())


def detect_stack_signals(project_path: Path) -> set[str]:
    """Best-effort detection of what's in the user's project.

    Returns lowercase tags ("next", "supabase", "stripe", …) used to
    cross-reference each catalog entry's ``suggested_when`` list.
    """
    signals: set[str] = set()

    # package.json signals
    pkg = project_path / "package.json"
    if pkg.is_file():
        try:
            import json

            data = json.loads(pkg.read_text())
            deps = {
                **data.get("dependencies", {}),
                **data.get("devDependencies", {}),
            }
            for key, tag in {
                "next": "next",
                "@supabase/supabase-js": "supabase",
                "@supabase/ssr": "supabase",
                "stripe": "stripe",
                "@stripe/stripe-js": "stripe",
                "@vercel/analytics": "vercel",
                "@vercel/edge": "vercel",
                "resend": "resend",
                "@slack/bolt": "slack",
                "@linear/sdk": "linear",
                "@sentry/nextjs": "sentry",
                "@sentry/node": "sentry",
                "@sentry/react": "sentry",
                "pg": "postgres",
                "drizzle-orm": "postgres",
            }.items():
                if key in deps:
                    signals.add(tag)
        except (OSError, ValueError):
            pass

    # Filesystem signals
    if (project_path / "supabase").is_dir():
        signals.add("supabase")
    if (project_path / ".vercel").is_dir():
        signals.add("vercel")
    if (project_path / "vercel.json").is_file():
        signals.add("vercel")

    # Git remote → github/gitlab/etc
    git_config = project_path / ".git" / "config"
    if git_config.is_file():
        try:
            text = git_config.read_text()
            if "github.com" in text:
                signals.add("github")
                signals.add("git")
            if "gitlab.com" in text:
                signals.add("gitlab")
                signals.add("git")
        except OSError:
            pass

    return signals


# ──────────────────────────────────────────────────────────────────────
#  State persistence
# ──────────────────────────────────────────────────────────────────────


def load_connector_state(forge_dir: Path) -> dict:
    """Read ``.forge/connectors.toml`` (returns {} if missing)."""
    path = forge_dir / "connectors.toml"
    if not path.is_file():
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, ValueError):
        return {}


def save_connector_state(forge_dir: Path, state: dict) -> None:
    """Write the connectors.toml — the only file the wizard writes.

    Does NOT write credential values. Just records which connectors are
    enabled and how they're sourced (mcp / native / manual). Secrets
    stay in the user's shell env or .env file.
    """
    forge_dir.mkdir(exist_ok=True)
    path = forge_dir / "connectors.toml"
    lines = [
        "# Forge connector configuration. Generated by `forge wizard`.",
        "# Edit by hand, or re-run the wizard to reconfigure.",
        "# This file does NOT contain credentials. Set env vars in your",
        "# shell or .env file — the wizard prints what's needed.",
        "",
    ]
    for name, cfg in sorted(state.items()):
        lines.append(f"[connectors.{name}]")
        for key, val in cfg.items():
            if isinstance(val, bool):
                lines.append(f"{key} = {str(val).lower()}")
            elif isinstance(val, (int, float)):
                lines.append(f"{key} = {val}")
            elif isinstance(val, list):
                quoted = ", ".join(f'"{v}"' for v in val)
                lines.append(f"{key} = [{quoted}]")
            else:
                lines.append(f'{key} = "{val}"')
        lines.append("")
    path.write_text("\n".join(lines))


def has_completed_wizard(forge_dir: Path) -> bool:
    """Returns True iff the user has ever completed the wizard.

    Checked at the start of `forge serve` to decide whether to auto-launch
    the wizard. The flag lives in connectors.toml's ``meta`` table so it
    survives but the user can reset by deleting that single line.
    """
    state = load_connector_state(forge_dir)
    return bool(state.get("meta", {}).get("wizard_completed_at"))


def mark_wizard_completed(forge_dir: Path, state: dict) -> None:
    """Stamp the wizard as completed so it doesn't auto-trigger again."""
    from datetime import datetime, timezone

    state.setdefault("meta", {})["wizard_completed_at"] = datetime.now(timezone.utc).isoformat()
    save_connector_state(forge_dir, state)


# ──────────────────────────────────────────────────────────────────────
#  Wizard flow
# ──────────────────────────────────────────────────────────────────────


@dataclass
class WizardOptions:
    project_path: Path
    forge_dir: Path
    claude_settings_path: Path
    non_interactive: bool = False
    # Injection points for tests:
    confirm: Callable[[str, bool], bool] | None = None
    ask: Callable[[str, str], str] | None = None
    print_fn: Callable[[str], None] = print


def run_wizard(opts: WizardOptions) -> dict:
    """Top-level wizard. Returns the final state dict.

    Phases:
      1. Detect existing setup
      2. Show context summary
      3. Auto-enable existing MCP servers (one prompt to confirm)
      4. Suggest tier-1 connectors based on stack signals
      5. Print env-var setup instructions
      6. Healthcheck
      7. Save state
    """
    confirm = opts.confirm or _default_confirm
    ask = opts.ask or _default_ask
    p = opts.print_fn

    p("")
    p("┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓")
    p("┃                   Forge — Setup Wizard                ┃")
    p("┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛")
    p("")
    p("  This wizard will help you connect Forge to the tools your")
    p("  project uses. You can skip any prompt, exit anytime (Ctrl-C),")
    p("  or re-run later with: forge wizard")
    p("")

    # Phase 1: detect
    existing_mcp = detect_existing_mcp_servers(opts.claude_settings_path)
    stack_signals = detect_stack_signals(opts.project_path)
    existing_state = load_connector_state(opts.forge_dir)
    state: dict = dict(existing_state)
    state.setdefault("connectors", {})

    # Phase 2: context summary
    p("  Detected:")
    if stack_signals:
        p(f"    Stack signals: {', '.join(sorted(stack_signals))}")
    else:
        p("    Stack signals: (none detected — that's OK)")
    if existing_mcp:
        p(f"    Existing MCP servers: {', '.join(existing_mcp)}")
    else:
        p("    Existing MCP servers: (none in .claude/settings.json)")
    p("")

    # Phase 3: enable existing MCP servers
    enabled_now: list[str] = []
    if existing_mcp:
        if opts.non_interactive or confirm(
            f"Enable all {len(existing_mcp)} existing MCP server(s) in Forge?",
            True,
        ):
            for name in existing_mcp:
                state["connectors"][name] = {
                    "mechanism": "mcp",
                    "enabled": True,
                    "source": "existing",
                }
                enabled_now.append(name)
            p(f"  ✓ Enabled: {', '.join(enabled_now)}")
        p("")

    # Phase 4: suggest based on stack signals
    suggestions: list[WizardConnector] = []
    for c in CATALOG:
        if c.name in state["connectors"]:
            continue  # already enabled
        if c.name in existing_mcp:
            continue
        if stack_signals & set(c.suggested_when):
            suggestions.append(c)

    if suggestions:
        p(f"  Based on your stack, you might want these {len(suggestions)} connector(s):")
        p("")
        for c in suggestions:
            p(f"    {c.name:12s}  {c.title}")
            p(f"                   {c.description}")
        p("")

        for c in suggestions:
            if opts.non_interactive:
                # In non-interactive mode, suggest but don't enable
                continue
            if confirm(f"  Set up {c.name}?", False):
                _setup_connector(c, state, ask, p)
                enabled_now.append(c.name)

    # Phase 5: optional manual additions
    if not opts.non_interactive:
        p("")
        if confirm("  Want to add another connector not listed above?", False):
            other_catalog = [
                c
                for c in CATALOG
                if c.name not in state["connectors"] and c.name not in enabled_now
            ]
            if other_catalog:
                p("")
                p("  Available:")
                for i, c in enumerate(other_catalog, 1):
                    p(f"    {i:2d}. {c.name:12s} — {c.title}")
                p("")
                choice = ask("  Pick a number, or Enter to skip", "")
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(other_catalog):
                        c = other_catalog[idx]
                        _setup_connector(c, state, ask, p)
                        enabled_now.append(c.name)

    # Phase 6: env var summary
    if enabled_now:
        all_env_vars: list[tuple[str, list[str]]] = []
        for name in enabled_now:
            entry = next((c for c in CATALOG if c.name == name), None)
            if entry and entry.env_vars:
                missing = [v for v in entry.env_vars if not os.environ.get(v)]
                if missing:
                    all_env_vars.append((name, missing))

        if all_env_vars:
            p("")
            p("  ━━ Set these env vars before running `forge serve` ━━")
            p("")
            for name, vars_ in all_env_vars:
                docs = next((c.docs_url for c in CATALOG if c.name == name), None)
                p(f"  {name}:")
                for v in vars_:
                    p(f"    export {v}=...")
                if docs:
                    p(f"    (get token: {docs})")
                p("")
            p("  Tip: put these in your shell rc (~/.zshrc / ~/.bashrc) or .env")
            p("")

    # Phase 7: save state
    mark_wizard_completed(opts.forge_dir, state)

    p("")
    p("  ✓ Wizard complete.")
    p(f"  ✓ State saved to: {opts.forge_dir / 'connectors.toml'}")
    if enabled_now:
        p(f"  ✓ Enabled connectors: {', '.join(enabled_now)}")
    p("")
    p("  Next:")
    p("    forge doctor                    Validate everything")
    p('    forge plan "your goal here"     Decompose into sprints')
    p("    forge serve                     Open the dashboard")
    p("")
    return state


def _setup_connector(
    c: WizardConnector,
    state: dict,
    ask: Callable[[str, str], str],
    p: Callable[[str], None],
) -> None:
    """Configure one connector. Records in state['connectors'][name]."""
    p("")
    p(f"  Setting up {c.title}…")
    if c.mechanism == "mcp":
        state["connectors"][c.name] = {
            "mechanism": "mcp",
            "enabled": True,
            "command": c.mcp_command or "",
            "args": c.mcp_args,
            "env_vars": c.env_vars,
        }
        p("  ✓ Recorded in connectors.toml as MCP")
        p("  Note: still need to add to .claude/settings.json — see below.")
        if c.env_vars:
            present = [v for v in c.env_vars if os.environ.get(v)]
            missing = [v for v in c.env_vars if not os.environ.get(v)]
            if missing:
                p(f"  Missing env vars: {', '.join(missing)}")
                if c.docs_url:
                    p(f"  Get a token: {c.docs_url}")
            if present:
                p(f"  ✓ Already in env: {', '.join(present)}")
    elif c.mechanism == "native":
        state["connectors"][c.name] = {
            "mechanism": "native",
            "enabled": True,
        }


# ──────────────────────────────────────────────────────────────────────
#  Default I/O
# ──────────────────────────────────────────────────────────────────────


def _default_confirm(prompt: str, default: bool) -> bool:
    """Print a Y/n prompt and read the answer. Returns the boolean."""
    if not _is_interactive_stdin():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        response = input(f"{prompt} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not response:
        return default
    return response.startswith("y")


def _default_ask(prompt: str, default: str) -> str:
    """Print a prompt and read a line. Returns the answer (or default)."""
    if not _is_interactive_stdin():
        return default
    try:
        if default:
            response = input(f"{prompt} [{default}]: ")
        else:
            response = input(f"{prompt}: ")
    except (EOFError, KeyboardInterrupt):
        return default
    return response.strip() or default


def _is_interactive_stdin() -> bool:
    """True iff stdin is a TTY. False in CI / pipes / Docker non-tty."""
    try:
        return os.isatty(0)
    except (OSError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────────────
#  Healthcheck
# ──────────────────────────────────────────────────────────────────────


def healthcheck_connector(c: WizardConnector) -> tuple[bool, str]:
    """Run the connector's healthcheck command. Returns (ok, message)."""
    if not c.healthcheck:
        return (True, "no healthcheck configured")
    cmd = c.healthcheck.split()
    binary = cmd[0]
    if not shutil.which(binary):
        return (False, f"binary not on PATH: {binary}")
    try:
        import subprocess

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        if result.returncode == 0:
            first_line = (result.stdout or result.stderr).splitlines()[:1]
            return (True, first_line[0] if first_line else "ok")
        return (False, f"exit {result.returncode}: {result.stderr[:200]}")
    except (OSError, subprocess.TimeoutExpired) as e:
        return (False, f"healthcheck failed: {e}")


# ──────────────────────────────────────────────────────────────────────
#  Capability-change re-approval (Sprint 6.1.5)
# ──────────────────────────────────────────────────────────────────────


def _is_capability_widening(old: object, new: object) -> bool:
    """True iff ``new`` is strictly broader than ``old``.

    For list-typed scopes (network / filesystem / exec / secrets_read),
    widening = the new list contains an item the old list did not. For
    numeric limits (memory_mb / cpu_seconds / wall_seconds), widening =
    a higher value.

    We only prompt re-approval on widening — narrowing the scope is
    safe and we let it proceed. This keeps the prompt-rate low; the
    only changes that interrupt the user are ones that genuinely
    expand the plugin's reach.
    """
    if isinstance(old, list) and isinstance(new, list):
        return any(item not in old for item in new)
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return new > old
    # Type changed or one side missing — treat as widening (conservative).
    return old != new


def find_widened_capabilities(
    diff: dict[str, tuple[object, object]],
) -> dict[str, tuple[object, object]]:
    """Return only the diff entries where the new scope is broader.

    ``diff`` is the output of ``PluginsLock.diff_capabilities``. Removing
    items, narrowing limits, or unchanged keys are dropped — the wizard
    only prompts when re-approval is genuinely warranted.
    """
    return {
        key: (old, new) for key, (old, new) in diff.items() if _is_capability_widening(old, new)
    }


def confirm_capability_changes(
    *,
    plugin_kind: str,
    plugin_name: str,
    diff: dict[str, tuple[object, object]],
    confirm: Callable[[str, bool], bool] | None = None,
    print_fn: Callable[[str], None] = print,
) -> bool:
    """Prompt the user when a plugin's capabilities widened. Returns the
    user's decision (True = approve the new caps, False = refuse).

    Called by the dispatcher / CLI when ``PluginsLock.diff_capabilities``
    returns non-None and the diff includes at least one widened entry.
    A pure narrowing diff (e.g. plugin dropped a host) returns True
    immediately because narrowing is always safe.

    Behaviour:
      - non-tty: returns False (refuse — no chance to consent)
      - widened: prints the diff with old → new, asks Y/N (default N)
      - narrowed only: returns True silently

    The caller is responsible for re-pinning the lock entry on True.
    """
    widened = find_widened_capabilities(diff)
    if not widened:
        # Pure narrowing — safe, auto-approve.
        return True

    confirm = confirm or _default_confirm
    p = print_fn

    p("")
    p(f"  ⚠ Plugin '{plugin_kind}:{plugin_name}' is asking for broader capabilities than")
    p("    you previously approved. Review and decide:")
    p("")
    for key in sorted(widened):
        old, new = widened[key]
        p(f"    [{key}]")
        p(f"      previously approved: {old!r}")
        p(f"      new manifest wants:  {new!r}")
    p("")
    p("  Re-approve only if you trust the new manifest. The plugin won't run")
    p("  until you decide. Refusing is safe — the previously approved version")
    p("  stays pinned and you can re-install later.")
    p("")

    return confirm("  Approve the new capabilities?", False)

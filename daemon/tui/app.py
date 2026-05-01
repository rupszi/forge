"""ForgeTUI — the main Textual application.

Layout (mirrors the Next.js dashboard's information density but in a
terminal-native form factor):

    ┌──────────────────────────────────────────────────────────────┐
    │ Forge ● Connected · qwen3-coder-next · Free (Ollama)         │  Header
    ├──────────────────────────────────────────────────────────────┤
    │ next │ typescript │ supabase │ vercel │ 12 KB items          │  Stack badges
    ├──────────────────────────────────────────────────────────────┤
    │ > Type / for commands, or describe what you want to build…   │  Prompt
    │ ┌──────────────────────────────────────────────────────────┐ │
    │ │                                                          │ │
    │ │                                                          │ │
    │ └──────────────────────────────────────────────────────────┘ │
    │ Auto mode · Normal · attach +                                │
    ├──────────────────────────────────────────────────────────────┤
    │ ───── Output ─────                                           │
    │ 14:32:01  session.start         build auth API              │  Output stream
    │ 14:32:03  plan.created          4 sprints                    │
    │ 14:32:08  sprint.attempt        [a1b2c3] attempt 1           │
    │ 14:32:14  sprint.evaluated      [a1b2c3] verdict: APPROVED   │
    │ 14:32:14  sprint.approved       [a1b2c3] ✓                   │
    └──────────────────────────────────────────────────────────────┘

Keybindings (Textual conventions):
  Enter           submit prompt
  Tab             cycle mode (auto → accept → plan → ask → bypass)
  Ctrl+L          clear output stream
  Ctrl+W          open browser dashboard alongside (companion mode)
  Ctrl+S          save session state
  Ctrl+Q / Ctrl+C quit
  /<cmd>          slash command (autocompletes)
"""

from __future__ import annotations

import logging
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    RichLog,
    Static,
)

from .ws_client import ForgeWSClient

logger = logging.getLogger(__name__)


class StackBadges(Static):
    """Renders detected framework / language / MCP servers as inline pills."""

    DEFAULT_CSS = """
    StackBadges {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    framework: reactive[str] = reactive("")
    language: reactive[str] = reactive("")
    mcp_servers: reactive[list[str]] = reactive(list)
    kb_count: reactive[int] = reactive(0)

    def render(self) -> str:
        bits: list[str] = []
        if self.framework:
            bits.append(f"[#c084fc on #2e1065] {self.framework} [/]")
        if self.language:
            bits.append(f"[#7dd3fc on #082f49] {self.language} [/]")
        for s in self.mcp_servers:
            bits.append(f"[#5eead4 on #042f2e] {s} [/]")
        if self.kb_count > 0:
            bits.append(f"[#fcd34d on #422006] {self.kb_count} KB items [/]")
        return " ".join(bits) if bits else "[dim](no project context yet)[/]"


class StatusBar(Static):
    """Bottom status bar — mode, transcript verbosity, connection, model, cost."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $boost;
        padding: 0 1;
        color: $text-muted;
    }
    """

    mode: reactive[str] = reactive("auto")
    verbosity: reactive[str] = reactive("normal")
    connected: reactive[bool] = reactive(False)
    model: reactive[str] = reactive("qwen3-coder-next")
    tier: reactive[str] = reactive("free")
    cost_usd: reactive[float] = reactive(0.0)

    def render(self) -> str:
        dot = "[#10b981]●[/]" if self.connected else "[#ef4444]●[/]"
        cost_text = f" · ${self.cost_usd:.4f}" if self.tier in ("metered",) else ""
        tier_label = {"free": "Free", "metered": "Metered", "subscription": "Plan"}.get(
            self.tier, self.tier
        )
        return (
            f"{dot} {'Connected' if self.connected else 'Disconnected'} "
            f"· [b]{self.mode}[/] · {self.verbosity} "
            f"· {self.model} ({tier_label}){cost_text}"
        )


class OutputStream(RichLog):
    """The live process-progression panel (Sprint 6.5 equivalent of the
    web dashboard's OutputStream component).

    Auto-scrolls; ring-buffered to 1000 lines. Color codes by event type
    using Rich markup.
    """

    DEFAULT_CSS = """
    OutputStream {
        background: $boost;
        border: solid $surface;
        height: 1fr;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(highlight=False, markup=True, max_lines=1000, **kwargs)

    def push_event(self, event: dict[str, Any]) -> None:
        ts = event.get("ts", "")[11:19] or "        "
        etype = event.get("type", "?")
        sprint_id = event.get("sprint_id") or ""
        data = event.get("data", {}) or {}

        sprint_short = ""
        if sprint_id:
            parts = sprint_id.split("-")
            sprint_short = f"[#a78bfa]\\[{(parts[1] if len(parts) > 1 else sprint_id)[:6]}][/]"

        color = self._color_for(etype)
        summary = self._summarize(etype, data)
        self.write(f"[dim]{ts}[/] [dim]{etype:<28}[/] {sprint_short}  [{color}]{summary}[/]")

    @staticmethod
    def _color_for(etype: str) -> str:
        if etype.startswith("sprint.approved") or etype == "sprint.recovered":
            return "#10b981"  # green
        if etype.startswith("sprint.crashed") or etype == "budget.exhausted":
            return "#ef4444"  # red
        if etype.startswith("sprint.revising") or etype.startswith("budget.downgrade"):
            return "#fbbf24"  # amber
        if etype.startswith("recovery."):
            return "#fb923c"  # orange
        if etype.startswith("plan.") or etype.startswith("session."):
            return "#60a5fa"  # blue
        if etype.startswith("sprint."):
            return "#c084fc"  # purple
        return "dim"

    @staticmethod
    def _summarize(etype: str, d: dict[str, Any]) -> str:
        match etype:
            case "session.start":
                return f"objective: {d.get('objective', '')}"
            case "session.complete":
                return (
                    f"done — {d.get('completed', 0)} ok, "
                    f"{d.get('failed', 0)} failed, "
                    f"${d.get('total_cost', 0.0):.4f}"
                )
            case "plan.created":
                return f"{d.get('sprint_count', '?')} sprint(s)"
            case "wave.start":
                return f"wave {d.get('wave', '?')} — {d.get('sprint_count', '?')} sprint(s)"
            case "worktree.created":
                return f"path: {d.get('path', '')}"
            case "sprint.attempt":
                return f"attempt {d.get('attempt', '?')}"
            case "sprint.evaluated":
                return (
                    f"verdict: {d.get('verdict', '?')} "
                    f"(in={d.get('tokens_in', 0)} out={d.get('tokens_out', 0)})"
                )
            case "sprint.approved":
                return "✓"
            case "sprint.revising":
                feedback = (d.get("feedback") or "")[:80]
                return f"revision {d.get('revision', '?')} — {feedback}"
            case "sprint.recovered":
                return f"✓ recovered via {d.get('sub_count', '?')} sub-sprints"
            case "sprint.crashed":
                return f"✗ {d.get('error', 'unknown')}"
            case _:
                if not d:
                    return ""
                # Brief JSON dump
                import json as _json

                s = _json.dumps(d, default=str)
                return s[:100] + ("…" if len(s) > 100 else "")


class PromptInput(Input):
    """The prompt textarea — submits on Enter, opens slash palette on '/'."""

    DEFAULT_CSS = """
    PromptInput {
        margin: 1 0;
    }
    """


class ForgeTUI(App):
    """Top-level Textual application."""

    CSS = """
    Screen {
        background: $background;
    }
    Header {
        background: $boost;
    }
    #stack {
        height: 1;
    }
    #output_container {
        height: 1fr;
        padding: 1 1 0 1;
    }
    #prompt_container {
        height: auto;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+l", "clear_output", "Clear", show=True),
        Binding("ctrl+w", "open_dashboard", "Dashboard", show=True),
        Binding("tab", "cycle_mode", "Cycle mode", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    TITLE = "Forge"
    SUB_TITLE = "Multi-agent coding orchestrator"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.client = ForgeWSClient()
        # Reactive state mirrors useForgeSocket.ts
        self._mode = "auto"
        self._verbosity = "normal"
        self._modes = ("auto", "accept_edits", "plan", "ask", "bypass")

    def compose(self) -> ComposeResult:
        yield Header()
        yield StackBadges(id="stack")
        with Vertical(id="output_container"):
            yield OutputStream(id="output")
        with Vertical(id="prompt_container"):
            yield PromptInput(
                placeholder="Type / for commands, or describe what you want to build…",
                id="prompt",
            )
            yield StatusBar(id="status")
        yield Footer()

    async def on_mount(self) -> None:
        # Subscribe to events the TUI cares about, then start the WS loop.
        self.client.subscribe("ws_connected", self._on_ws_connected)
        self.client.subscribe("ws_disconnected", self._on_ws_disconnected)
        self.client.subscribe("project_context", self._on_project_context)
        self.client.subscribe("tier_changed", self._on_tier_changed)
        self.client.subscribe("mode_changed", self._on_mode_changed)
        self.client.subscribe("budget_update", self._on_budget_update)
        self.client.subscribe("error", self._on_error)
        # Wildcard handler routes every event to the OutputStream
        self.client.subscribe("*", self._on_any_event)
        self._connect_worker()

    @work
    async def _connect_worker(self) -> None:
        await self.client.connect()

    # ── Event handlers ────────────────────────────────────────────

    async def _on_ws_connected(self, _msg: dict) -> None:
        status = self.query_one("#status", StatusBar)
        status.connected = True
        await self.client.send({"type": "init", "path": "."})

    async def _on_ws_disconnected(self, _msg: dict) -> None:
        status = self.query_one("#status", StatusBar)
        status.connected = False

    async def _on_project_context(self, msg: dict) -> None:
        stack = self.query_one("#stack", StackBadges)
        stack.framework = msg.get("framework", "")
        stack.language = msg.get("language", "")
        stack.mcp_servers = [s.get("name", "") for s in msg.get("mcp_servers", [])]
        stack.kb_count = msg.get("knowledge_count", 0)
        status = self.query_one("#status", StatusBar)
        if msg.get("billing_tier"):
            status.tier = msg["billing_tier"]

    async def _on_tier_changed(self, msg: dict) -> None:
        status = self.query_one("#status", StatusBar)
        status.tier = msg.get("tier", status.tier)

    async def _on_mode_changed(self, msg: dict) -> None:
        new_mode = msg.get("mode", "auto")
        self._mode = new_mode
        status = self.query_one("#status", StatusBar)
        status.mode = new_mode

    async def _on_budget_update(self, msg: dict) -> None:
        status = self.query_one("#status", StatusBar)
        status.cost_usd = msg.get("spent_usd", 0.0)

    async def _on_error(self, msg: dict) -> None:
        out = self.query_one("#output", OutputStream)
        out.write(f"[#ef4444]ERROR[/] {msg.get('error', '')}")

    async def _on_any_event(self, msg: dict) -> None:
        etype = msg.get("type", "")
        # Filter out the connection-lifecycle pseudo-events the WS client emits
        if etype in ("ws_connected", "ws_disconnected"):
            return
        # Stream-event detection mirrors useForgeSocket.ts
        prefixes = (
            "sprint.",
            "recovery.",
            "budget.",
            "plan.",
            "session.",
            "wave.",
            "worktree.",
            "repomap.",
        )
        if any(etype.startswith(p) for p in prefixes):
            out = self.query_one("#output", OutputStream)
            out.push_event(msg)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        prompt = self.query_one("#prompt", PromptInput)
        prompt.value = ""

        if text.startswith("/"):
            await self._handle_slash(text[1:])
        else:
            await self.client.send({"type": "plan", "objective": text})
            out = self.query_one("#output", OutputStream)
            out.write(f"[#a78bfa]>[/] {text}")

    async def _handle_slash(self, cmd_line: str) -> None:
        parts = cmd_line.split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1] if len(parts) > 1 else ""
        out = self.query_one("#output", OutputStream)

        match cmd:
            case "help":
                out.write(
                    "[dim]Commands: /help /clear /mode /model /memory /research "
                    "/review /budget /wizard /connectors /skills /llms /quit[/]"
                )
            case "clear":
                out.clear()
            case "mode":
                if arg in self._modes:
                    await self.client.send({"type": "set_mode", "mode": arg})
                else:
                    out.write(f"[#ef4444]Unknown mode: {arg}[/] — try {self._modes}")
            case "model":
                await self.client.send({"type": "set_model", "model": arg})
            case "quit":
                self.exit()
            case _:
                # Forward to daemon — the slash-command handler in ws_server
                # acks unknown ones gracefully.
                await self.client.send({"type": f"slash.{cmd}", "args": arg})

    # ── Bindings ──────────────────────────────────────────────────

    def action_clear_output(self) -> None:
        self.query_one("#output", OutputStream).clear()

    def action_open_dashboard(self) -> None:
        import webbrowser

        webbrowser.open("http://localhost:3000")

    async def action_cycle_mode(self) -> None:
        idx = self._modes.index(self._mode) if self._mode in self._modes else 0
        next_mode = self._modes[(idx + 1) % len(self._modes)]
        await self.client.send({"type": "set_mode", "mode": next_mode})

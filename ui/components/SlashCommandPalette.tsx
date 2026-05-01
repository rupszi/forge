/**
 * SlashCommandPalette — Claude-Code-style "/" command launcher.
 *
 * Triggered by typing "/" in the prompt input or via the AttachMenu.
 * Each command dispatches a WebSocket event to the daemon.
 *
 * Built-in commands (extensible — third-party plugins can register more
 * via daemon/connectors with side_effects="readonly"):
 *
 *   /help                  Show all available commands
 *   /clear                 Clear current session's transcript view
 *   /model <name>          Switch active model
 *   /mode <ask|auto|...>   Switch permission mode
 *   /memory                Open KB browser
 *   /memory search <q>     Search the KB inline
 *   /research <query>      Trigger manual web research
 *   /review <sprint-id>    Run multi-perspective review
 *   /replay <session-id>   Render a past session's trace
 *   /budget                Show budget detail
 *   /wizard                Re-run the connector setup wizard
 *   /connectors            List enabled connectors
 *   /skills                List installed skills
 *   /llms                  List configured LLM providers
 *   /diff                  Show all worktree diffs
 *   /merge                 Open the merge gate
 *   /reset                 Clear current sprints (keeps KB)
 *   /quit                  Stop the daemon
 */

import React, { useEffect, useMemo, useRef, useState } from "react";

export type SlashCommand = {
  name: string;          // canonical trigger after the "/"
  args?: string;         // free-form arg hint
  description: string;
  handler: (args: string) => void;
};

export type SlashPaletteProps = {
  open: boolean;
  query: string;          // text after the "/"
  onClose: () => void;
  onSelect: (cmd: SlashCommand, args: string) => void;
  commands: SlashCommand[];
};

export function SlashCommandPalette(props: SlashPaletteProps) {
  const { open, query, onClose, onSelect, commands } = props;
  const [highlight, setHighlight] = useState(0);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands.slice(0, 12);
    return commands
      .filter((c) => c.name.toLowerCase().startsWith(q.split(" ")[0]))
      .slice(0, 12);
  }, [query, commands]);

  useEffect(() => {
    setHighlight(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => Math.min(matches.length - 1, h + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => Math.max(0, h - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const cmd = matches[highlight];
        if (cmd) {
          const args = query.split(" ").slice(1).join(" ");
          onSelect(cmd, args);
        }
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, matches, highlight, query, onSelect, onClose]);

  if (!open) return null;

  return (
    <div className="absolute bottom-full mb-2 left-0 w-96 max-h-80 overflow-y-auto rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50">
      <div className="px-3 py-2 border-b border-[#1e1e2e] flex items-center justify-between">
        <span className="text-xs text-gray-500">Slash commands</span>
        <span className="text-[10px] text-gray-600">↑↓ Enter Esc</span>
      </div>
      {matches.length === 0 ? (
        <div className="px-3 py-4 text-sm text-gray-500 text-center">No matches</div>
      ) : (
        <ul>
          {matches.map((c, i) => (
            <li
              key={c.name}
              className={`px-3 py-2 cursor-pointer ${
                i === highlight ? "bg-[#1a1a24]" : "hover:bg-[#1a1a24]"
              }`}
              onMouseEnter={() => setHighlight(i)}
              onClick={() => {
                const args = query.split(" ").slice(1).join(" ");
                onSelect(c, args);
              }}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-purple-300">
                  /{c.name}
                  {c.args && <span className="text-gray-500 ml-2">{c.args}</span>}
                </span>
              </div>
              <p className="text-[11px] text-gray-500 mt-0.5">{c.description}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Default Forge command set. Each handler is a thin wrapper around the
 * WebSocket "send" function — passed in via the parent (page.tsx) so
 * commands have access to the live socket without a global.
 */
export function buildDefaultCommands(send: (msg: any) => void): SlashCommand[] {
  return [
    { name: "help",      description: "Show all available commands",       handler: () => send({ type: "slash.help" }) },
    { name: "clear",     description: "Clear current transcript",          handler: () => send({ type: "slash.clear" }) },
    { name: "model",     args: "<name>", description: "Switch active model",  handler: (a) => send({ type: "set_model", model: a }) },
    { name: "mode",      args: "<ask|accept|plan|auto|bypass>", description: "Switch permission mode", handler: (a) => send({ type: "set_mode", mode: a }) },
    { name: "memory",    args: "[search <q>]", description: "Open KB browser or search inline", handler: (a) => send({ type: "memory", action: a || "list" }) },
    { name: "research",  args: "<query>", description: "Manual web research", handler: (a) => send({ type: "research", query: a }) },
    { name: "review",    args: "<sprint-id>", description: "Multi-perspective review", handler: (a) => send({ type: "review", sprint_id: a }) },
    { name: "replay",    args: "<session-id>", description: "Render a past session's trace", handler: (a) => send({ type: "replay", session_id: a }) },
    { name: "budget",    description: "Show budget detail",                handler: () => send({ type: "budget.show" }) },
    { name: "wizard",    description: "Re-run the connector setup wizard", handler: () => send({ type: "wizard" }) },
    { name: "connectors", description: "List enabled connectors",          handler: () => send({ type: "connectors.list" }) },
    { name: "skills",    description: "List installed skills",             handler: () => send({ type: "skills.list" }) },
    { name: "llms",      description: "List configured LLM providers",     handler: () => send({ type: "llms.list" }) },
    { name: "diff",      description: "Show all worktree diffs",           handler: () => send({ type: "diff.show" }) },
    { name: "merge",     description: "Open the merge gate",               handler: () => send({ type: "merge.show" }) },
    { name: "reset",     description: "Clear current sprints (keeps KB)",  handler: () => send({ type: "reset" }) },
    { name: "quit",      description: "Stop the daemon",                   handler: () => send({ type: "quit" }) },
  ];
}

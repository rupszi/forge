/**
 * ModePicker — Claude-Code-style permission-mode dropdown.
 *
 * Maps to Forge's safety + autonomy tiers:
 *
 *   Ask permissions   → every destructive op + every write requires user OK
 *                       (mirrors Claude Code's strictest mode; useful when
 *                       you're letting a generator touch a prod repo for
 *                       the first time)
 *   Accept edits      → file writes auto-approved; destructive ops still
 *                       prompt (the everyday-IDE mode)
 *   Plan mode         → planner + evaluator only, no generator writes
 *                       (sketch+critique without committing to anything)
 *   Auto mode         → end-to-end autonomous; only "block"-severity ops
 *                       from daemon/safety.py prompt the user (default)
 *   Bypass            → no prompts; for power users who pair with strict
 *                       worktree+sandbox isolation. Logged extra-loudly.
 *
 * Keyboard shortcut: ⌘ + M opens the picker; 1–5 selects the mode.
 *
 * The mode is sent to the daemon as ``{type: "set_mode", mode: "..."}``.
 * The daemon enforces it at the scheduler boundary — UI mode picker is
 * a UX surface, not a security boundary.
 */

import React, { useEffect, useState } from "react";

export type Mode = "ask" | "accept_edits" | "plan" | "auto" | "bypass";

const MODES: { id: Mode; label: string; key: string; description: string; danger?: boolean }[] = [
  {
    id: "ask",
    label: "Ask permissions",
    key: "1",
    description: "Prompt before every write or destructive op. Strictest.",
  },
  {
    id: "accept_edits",
    label: "Accept edits",
    key: "2",
    description: "File writes auto-approved; destructive ops still prompt.",
  },
  {
    id: "plan",
    label: "Plan mode",
    key: "3",
    description: "Planner + evaluator only. No generator writes.",
  },
  {
    id: "auto",
    label: "Auto mode",
    key: "4",
    description: "End-to-end autonomous. Only block-severity ops prompt.",
  },
  {
    id: "bypass",
    label: "Bypass permissions",
    key: "5",
    description: "No prompts at all. For sandboxed environments only.",
    danger: true,
  },
];

export type ModePickerProps = {
  current: Mode;
  onChange: (mode: Mode) => void;
};

export function ModePicker({ current, onChange }: ModePickerProps) {
  const [open, setOpen] = useState(false);
  const currentLabel = MODES.find((m) => m.id === current)?.label ?? "Auto mode";

  // Keyboard: ⌘+M toggles, 1-5 picks while open
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.metaKey && e.key.toLowerCase() === "m") {
        e.preventDefault();
        setOpen((o) => !o);
        return;
      }
      if (open && /^[1-5]$/.test(e.key)) {
        const mode = MODES[parseInt(e.key, 10) - 1];
        if (mode) {
          onChange(mode.id);
          setOpen(false);
        }
      }
      if (open && e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onChange]);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`text-xs px-2 py-1 rounded transition-colors ${
          current === "bypass"
            ? "text-red-400 hover:bg-red-900/20"
            : current === "ask"
            ? "text-amber-300 hover:bg-amber-900/20"
            : "text-purple-300 hover:bg-purple-900/20"
        }`}
        title="Permission mode (⌘ M)"
      >
        {currentLabel}
      </button>

      {open && (
        <div className="absolute top-full mt-2 left-0 w-72 rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50">
          <div className="px-3 py-2 flex items-center justify-between border-b border-[#1e1e2e]">
            <span className="text-xs text-gray-500">Mode</span>
            <div className="flex items-center gap-1 text-[10px] text-gray-600">
              <kbd className="px-1 py-0.5 rounded bg-[#1e1e2e]">⇧</kbd>
              <kbd className="px-1 py-0.5 rounded bg-[#1e1e2e]">⌘</kbd>
              <kbd className="px-1 py-0.5 rounded bg-[#1e1e2e]">M</kbd>
            </div>
          </div>
          <ul className="py-1">
            {MODES.map((m) => (
              <li key={m.id}>
                <button
                  onClick={() => {
                    onChange(m.id);
                    setOpen(false);
                  }}
                  className={`w-full px-3 py-2 flex items-center justify-between text-left hover:bg-[#1a1a24] ${
                    m.danger ? "text-red-400" : "text-gray-200"
                  }`}
                >
                  <div className="flex flex-col">
                    <span className="text-sm">{m.label}</span>
                    <span className="text-[10px] text-gray-500">{m.description}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.id === current && <span className="text-green-400 text-sm">✓</span>}
                    <kbd className="text-[10px] px-1 py-0.5 rounded bg-[#1e1e2e] text-gray-500">
                      {m.key}
                    </kbd>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

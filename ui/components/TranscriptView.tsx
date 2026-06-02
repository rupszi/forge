/**
 * TranscriptView picker — Claude-Code-style transcript verbosity selector.
 *
 *   Normal    → user-visible messages + tool results (default)
 *   Thinking  → adds the model's chain-of-thought (when available)
 *   Verbose   → adds every tool call, every event, every retry
 *   Summary   → collapses each sprint to its 1-line outcome
 *
 * Forge maps these to filtering on the trace.jsonl event stream
 * (daemon/replay.py / daemon/events.py). The actual filtering happens
 * client-side so changing the view is instant; the underlying stream
 * is unaltered.
 *
 * Keyboard: ⌃ + O opens the picker; 1-4 picks.
 */

import React, { useEffect, useState } from "react";

export type Verbosity = "normal" | "thinking" | "verbose" | "summary";

const OPTIONS: { id: Verbosity; label: string; description: string }[] = [
  { id: "normal",   label: "Normal",   description: "User messages + tool results" },
  { id: "thinking", label: "Thinking", description: "Adds model chain-of-thought" },
  { id: "verbose",  label: "Verbose",  description: "Every event, every retry" },
  { id: "summary",  label: "Summary",  description: "1 line per sprint" },
];

export type TranscriptViewProps = {
  current: Verbosity;
  onChange: (v: Verbosity) => void;
};

export function TranscriptView({ current, onChange }: TranscriptViewProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (open && /^[1-4]$/.test(e.key)) {
        const opt = OPTIONS[parseInt(e.key, 10) - 1];
        if (opt) {
          onChange(opt.id);
          setOpen(false);
        }
      }
      if (open && e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onChange]);

  const currentLabel = OPTIONS.find((o) => o.id === current)?.label ?? "Normal";

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-xs px-2 py-1 rounded text-gray-400 hover:bg-[#1a1a24] hover:text-gray-200"
        title="Transcript view (⌃ O)"
      >
        {currentLabel}
      </button>

      {open && (
        <div className="absolute top-full mt-2 right-0 w-60 rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50">
          <div className="px-3 py-2 flex items-center justify-between border-b border-[#1e1e2e]">
            <span className="text-xs text-gray-500">Transcript view</span>
            <div className="flex items-center gap-1 text-[10px] text-gray-600">
              <kbd className="px-1 py-0.5 rounded bg-[#1e1e2e]">⌃</kbd>
              <kbd className="px-1 py-0.5 rounded bg-[#1e1e2e]">O</kbd>
            </div>
          </div>
          <ul className="py-1">
            {OPTIONS.map((o) => (
              <li key={o.id}>
                <button
                  onClick={() => {
                    onChange(o.id);
                    setOpen(false);
                  }}
                  className="w-full px-3 py-2 flex items-center justify-between text-left hover:bg-[#1a1a24]"
                >
                  <div className="flex flex-col">
                    <span className="text-sm text-gray-200">{o.label}</span>
                    <span className="text-[10px] text-gray-500">{o.description}</span>
                  </div>
                  {o.id === current && <span className="text-green-400 text-sm">✓</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

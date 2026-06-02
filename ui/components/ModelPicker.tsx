"use client";

import { useEffect, useRef, useState } from "react";

export type ModelPickerProps = {
  current: string;
  models: { name: string; size: string }[];
  onChange: (model: string) => void;
};

/**
 * Click the active-model label (top-right) to switch to any pulled Ollama
 * model. Populated from the daemon's `models.installed` (real `ollama list`).
 * Opens downward, closes on outside-click / Escape.
 */
export function ModelPicker({ current, models, onChange }: ModelPickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Switch model"
        className="text-gray-300 font-mono text-[11px] hover:text-white underline decoration-dotted underline-offset-2"
      >
        {current} ▾
      </button>
      {open && (
        <div className="absolute top-full mt-1 right-0 w-64 max-h-80 overflow-auto rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50">
          {models.length === 0 ? (
            <div className="px-3 py-3 text-[11px] text-gray-500">
              No models pulled. Run <span className="font-mono text-gray-300">forge models pull</span>.
            </div>
          ) : (
            <ul className="py-1">
              {models.map((m) => (
                <li key={m.name}>
                  <button
                    onClick={() => {
                      onChange(m.name);
                      setOpen(false);
                    }}
                    className="w-full px-3 py-1.5 flex items-center justify-between text-left hover:bg-[#1a1a24]"
                  >
                    <span
                      className={`text-xs font-mono ${
                        m.name === current ? "text-purple-300" : "text-gray-200"
                      }`}
                    >
                      {m.name}
                    </span>
                    <span className="text-[10px] text-gray-600">{m.size}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

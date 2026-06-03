"use client";

import { useEffect, useRef, useState } from "react";

import type { BenchProfileOption } from "@/lib/types";

export type BenchProfileSelectProps = {
  profiles: BenchProfileOption[];
  selected: string;
  onChange: (value: string) => void;
};

/**
 * SWE-bench kill-gate profile dropdown. Each profile bundles metric tiers by
 * cost — the option shows its run multiplier and the tiers it computes so the
 * user sees the trade-off (gate 1× → diagnostic 1× → baseline 2× → full N×)
 * before committing to an expensive run.
 */
export function BenchProfileSelect({ profiles, selected, onChange }: BenchProfileSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  if (!profiles.length) return null;

  const current = profiles.find((p) => p.value === selected) ?? profiles[0];

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="SWE-bench metric profile"
        className="text-gray-400 text-[11px] hover:text-white underline decoration-dotted underline-offset-2"
      >
        bench: {current.label} (~{current.cost_multiplier}×) ▾
      </button>
      {open && (
        <div className="absolute top-full mt-1 right-0 w-80 rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50 py-1">
          {profiles.map((p) => (
            <button
              key={p.value}
              onClick={() => {
                onChange(p.value);
                setOpen(false);
              }}
              className="w-full px-3 py-2 text-left hover:bg-[#1a1a24]"
            >
              <div className="flex items-center justify-between">
                <span
                  className={`text-xs ${p.value === selected ? "text-purple-300" : "text-gray-200"}`}
                >
                  {p.label}
                </span>
                <span className="text-[10px] text-gray-600">~{p.cost_multiplier}× runs</span>
              </div>
              <div className="mt-0.5 text-[10px] text-gray-500 leading-snug">{p.description}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                {p.tiers.map((t, i) => (
                  <span
                    key={t}
                    title={p.tier_labels[i]}
                    className="px-1.5 py-0.5 rounded bg-[#1a1a24] border border-[#1e1e2e] text-[9px] text-gray-400"
                  >
                    T{t}
                  </span>
                ))}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

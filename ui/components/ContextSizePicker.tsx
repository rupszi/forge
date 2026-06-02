"use client";

import { useEffect, useRef, useState } from "react";

import type { ContextOptions } from "@/lib/types";

export type ContextSizePickerProps = {
  options: ContextOptions | null;
  onChange: (value: number | "auto") => void;
  onKvChange?: (value: string) => void;
};

/**
 * Context-window (num_ctx) dropdown. Presets above the model's trained max or
 * the RAM-safe ceiling are disabled; each shows its approx KV-cache cost.
 * "Auto" picks the largest preset that safely fits the current model + RAM.
 */
export function ContextSizePicker({ options, onChange, onKvChange }: ContextSizePickerProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  if (!options) return null;

  const human = (t: number) =>
    t % (1024 * 1024) === 0 ? `${t / (1024 * 1024)}M` : `${Math.round(t / 1024)}K`;

  const label =
    options.setting === "auto"
      ? `Auto (${human(options.auto)})`
      : human(options.setting as number);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Context window (num_ctx)"
        className="text-gray-400 text-[11px] hover:text-white underline decoration-dotted underline-offset-2"
      >
        ctx {label} ▾
      </button>
      {open && (
        <div className="absolute top-full mt-1 right-0 w-60 rounded-lg bg-[#12121a] border border-[#1e1e2e] shadow-xl z-50 py-1">
          <button
            onClick={() => {
              onChange("auto");
              setOpen(false);
            }}
            className="w-full px-3 py-1.5 flex items-center justify-between text-left hover:bg-[#1a1a24]"
          >
            <span className={`text-xs ${options.setting === "auto" ? "text-purple-300" : "text-gray-200"}`}>
              Auto (max safe)
            </span>
            <span className="text-[10px] text-gray-600">{Math.round(options.auto / 1024)}K</span>
          </button>
          <div className="my-1 border-t border-[#1e1e2e]" />
          {options.presets.map((p) => {
            const disabled = !p.fits || p.exceeds_model;
            const reason = p.exceeds_model ? "above model max" : !p.fits ? "needs more RAM" : "";
            return (
              <button
                key={p.tokens}
                disabled={disabled}
                onClick={() => {
                  onChange(p.tokens);
                  setOpen(false);
                }}
                title={reason}
                className={`w-full px-3 py-1.5 flex items-center justify-between text-left ${
                  disabled ? "opacity-40 cursor-not-allowed" : "hover:bg-[#1a1a24]"
                }`}
              >
                <span
                  className={`text-xs ${
                    options.setting === p.tokens ? "text-purple-300" : "text-gray-200"
                  }`}
                >
                  {p.label}
                </span>
                <span className="text-[10px] text-gray-600">
                  {reason ? reason : `~${p.kv_gb} GB`}
                </span>
              </button>
            );
          })}

          {onKvChange && options.kv_cache_types?.length > 0 && (
            <>
              <div className="my-1 border-t border-[#1e1e2e]" />
              <div className="px-3 py-1.5">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] text-gray-500">KV cache</span>
                  <span className="text-[9px] text-gray-600">q8/q4 → more context</span>
                </div>
                <div className="flex gap-1">
                  {options.kv_cache_types.map((t) => (
                    <button
                      key={t}
                      onClick={() => onKvChange(t)}
                      className={`px-2 py-0.5 rounded text-[10px] border ${
                        options.kv_cache_type === t
                          ? "border-purple-600 text-purple-300"
                          : "border-[#1e1e2e] text-gray-400 hover:bg-[#1a1a24]"
                      }`}
                    >
                      {t === "f16" ? "f16" : t === "q8_0" ? "q8" : "q4"}
                    </button>
                  ))}
                </div>
                <div className="mt-1 text-[9px] text-gray-600">
                  match your Ollama server (OLLAMA_KV_CACHE_TYPE)
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

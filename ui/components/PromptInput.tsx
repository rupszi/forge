"use client";

import { useState } from "react";

interface Props {
  onSubmit: (objective: string) => void;
  /** Optional change callback so parents can detect "/" trigger for slash commands. */
  onChange?: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function PromptInput({
  onSubmit,
  onChange,
  disabled,
  placeholder = "Type / for commands, or describe what you want to build…",
}: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (value.trim() && !disabled) {
      onSubmit(value.trim());
      setValue("");
      onChange?.("");
    }
  };

  return (
    <div className="relative">
      <textarea
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          onChange?.(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
        }}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full h-24 px-4 py-3 rounded-lg bg-[#12121a] border border-[#1e1e2e] text-white placeholder-gray-600 resize-none focus:outline-none focus:border-purple-600 disabled:opacity-50 text-sm font-mono"
      />
      <button
        onClick={handleSubmit}
        disabled={disabled || !value.trim()}
        className="absolute bottom-3 right-3 px-4 py-1.5 text-sm rounded bg-purple-600 text-white hover:bg-purple-500 disabled:opacity-30 disabled:hover:bg-purple-600 transition-colors"
      >
        {value.trim().startsWith("/") ? "Run" : "Plan"}
      </button>
    </div>
  );
}

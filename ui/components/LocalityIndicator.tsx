"use client";

import type { LocalityState } from "@/lib/types";

/**
 * Honest local-first badge. Daemon-sourced (daemon/locality.py) so it can't
 * drift from reality: "Local-only ●" when no cloud opt-in, "Cloud enabled ▲"
 * when the user explicitly turned cloud on (FORGE_CLOUD_ENABLED).
 */
export function LocalityIndicator({ locality }: { locality: LocalityState }) {
  const local = locality.mode === "local";
  return (
    <span
      title={
        local
          ? "All inference runs locally. Zero outbound calls."
          : "Cloud models enabled (FORGE_CLOUD_ENABLED). Some calls leave this machine."
      }
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        fontFamily: "var(--font-mono, monospace)",
        padding: "2px 8px",
        borderRadius: 999,
        border: `1px solid ${local ? "#1f9d6b" : "#c47f17"}`,
        color: local ? "#1f9d6b" : "#c47f17",
        background: local ? "rgba(31,157,107,0.08)" : "rgba(196,127,23,0.08)",
      }}
    >
      {local ? "● Local-only" : "▲ Cloud enabled"}
    </span>
  );
}

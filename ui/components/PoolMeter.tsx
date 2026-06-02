"use client";

import type { PoolState } from "@/lib/types";

/**
 * Live model-pool RAM meter (daemon/pool.py). Shows resident GB vs the budget
 * and which models are loaded — pinned (orchestrator/embeddings) and in-use
 * (a coder/evaluator spawned for a sprint). Makes the "spawn on demand, evict
 * under budget" behavior visible.
 */
export function PoolMeter({ pool }: { pool: PoolState | null }) {
  if (!pool || pool.budget_gb <= 0) return null;
  const pct = Math.min(100, Math.round((pool.resident_gb / pool.budget_gb) * 100));
  const hot = pct >= 85;
  return (
    <div style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 12, minWidth: 180 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span>Model RAM</span>
        <span style={{ color: hot ? "#c0392b" : "inherit" }}>
          {pool.resident_gb.toFixed(1)} / {pool.budget_gb.toFixed(0)} GB
        </span>
      </div>
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: "rgba(127,127,127,0.2)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: hot ? "#c0392b" : "#2f80ed",
            transition: "width 200ms ease",
          }}
        />
      </div>
      {pool.models.length > 0 && (
        <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 4 }}>
          {pool.models.map((m) => (
            <span
              key={m.name}
              title={`${m.size_gb.toFixed(1)} GB${m.pinned ? " · pinned" : ""}${
                m.in_use ? ` · in use ×${m.in_use}` : ""
              }`}
              style={{
                padding: "1px 6px",
                borderRadius: 4,
                fontSize: 11,
                border: "1px solid rgba(127,127,127,0.3)",
                opacity: m.in_use ? 1 : 0.6,
                fontWeight: m.pinned ? 600 : 400,
              }}
            >
              {m.pinned ? "📌 " : ""}
              {m.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

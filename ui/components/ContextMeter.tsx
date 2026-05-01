/**
 * ContextMeter — Claude-Code-style context-window + budget meter.
 *
 * Renders three things in the header strip:
 *
 *   1. Context window used / cap with a progress bar (replaces the
 *      mostly-meaningless "$0.00 / $5.00" display when the user is on
 *      Ollama-only mode where every spend is $0).
 *   2. Plan / 5-hour-limit / weekly-limit usage bars (only shown when
 *      the active model has subscription-based metering — i.e. Claude
 *      Anthropic plans). Hidden for pure Ollama / vLLM sessions.
 *   3. Current model + tier badge ("qwen3-coder-next · Auto" or
 *      "claude-sonnet-4-7 1M · Extra high").
 *
 * Why this replaces the $ meter:
 *   - For Ollama users the $ meter always reads $0.00 and is
 *     informational noise.
 *   - For Anthropic users the $ meter is one signal but plan-tier
 *     usage is what they actually want to monitor (rate-limit pressure
 *     vs hard wallet cap).
 *   - The context-window meter is universally useful — every model
 *     has a context window, and "how full is it" is the question that
 *     drives compaction / repomap-trim decisions.
 */

import React from "react";

export type Tier = "free" | "metered" | "subscription";

export type ContextMeterProps = {
  contextUsed: number;        // tokens used in the current sprint context
  contextCap: number;         // model's context window
  costUsd: number;            // accumulated $ spend this session (0 for Ollama)
  budgetUsd: number;          // session $ cap (from BudgetController)
  model: string;              // active model identifier
  // Tier comes from the daemon (billing.py::detect_tier). When undefined,
  // we fall back to a conservative "free" — the daemon ALWAYS sends one,
  // so undefined means "not connected yet" and we shouldn't guess.
  tier?: Tier;
  // Subscription metering (only populated for Anthropic plan-based clients)
  planUsage?: {
    fiveHour?: { used: number; resetsInHours: number };  // 0..1
    weekly?: { used: number; resetsInDays: number };     // 0..1
    weeklyClaudeDesign?: { used: number };
    sonnetOnly?: { used: number };
  };
};

export function ContextMeter(props: ContextMeterProps) {
  const {
    contextUsed,
    contextCap,
    costUsd,
    budgetUsd,
    model,
    tier = "free",  // Conservative default — daemon ALWAYS sends one; this
                    // is just for the moments before connect lands.
    planUsage,
  } = props;

  const ctxFraction = contextCap > 0 ? contextUsed / contextCap : 0;
  const ctxPct = Math.min(100, Math.round(ctxFraction * 100));

  return (
    <div className="flex items-center gap-4 text-xs text-gray-400">
      {/* Context window meter — always shown */}
      <div className="flex items-center gap-2">
        <span className="text-gray-500">Context</span>
        <div className="w-24 h-1.5 rounded-full bg-[#1e1e2e] overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${barColor(ctxFraction)}`}
            style={{ width: `${ctxPct}%` }}
          />
        </div>
        <span className="tabular-nums">
          {formatTokens(contextUsed)} / {formatTokens(contextCap)} ({ctxPct}%)
        </span>
      </div>

      {/* Cost meter — only shown for metered tier (paid API) */}
      {tier === "metered" && (
        <div className="flex items-center gap-2 border-l border-[#1e1e2e] pl-4">
          <span className="text-gray-500">Spend</span>
          <span className="tabular-nums">
            ${costUsd.toFixed(2)} / ${budgetUsd.toFixed(2)}
          </span>
          <div className="w-16 h-1.5 rounded-full bg-[#1e1e2e] overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${barColor(costUsd / budgetUsd)}`}
              style={{ width: `${Math.min(100, (costUsd / budgetUsd) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Subscription plan-tier bars — only for subscription mode */}
      {tier === "subscription" && planUsage && (
        <div className="flex items-center gap-3 border-l border-[#1e1e2e] pl-4">
          {planUsage.fiveHour && (
            <PlanBar
              label="5h"
              used={planUsage.fiveHour.used}
              resetsLabel={`resets ${planUsage.fiveHour.resetsInHours}h`}
            />
          )}
          {planUsage.weekly && (
            <PlanBar
              label="Weekly"
              used={planUsage.weekly.used}
              resetsLabel={`resets ${planUsage.weekly.resetsInDays}d`}
            />
          )}
        </div>
      )}

      {/* Free tier — show "Free (Ollama)" badge */}
      {tier === "free" && (
        <div className="flex items-center gap-2 border-l border-[#1e1e2e] pl-4">
          <span className="px-1.5 py-0.5 text-[10px] rounded bg-teal-900/40 text-teal-300 border border-teal-800/30">
            Free (Ollama)
          </span>
        </div>
      )}

      {/* Model badge at the very right */}
      <div className="flex items-center gap-2 border-l border-[#1e1e2e] pl-4">
        <span className="text-gray-300 font-mono text-[11px]">{model}</span>
        <span className="text-gray-500">·</span>
        <span className="text-gray-400 text-[11px]">
          {tierBadge(tier)}
        </span>
      </div>
    </div>
  );
}

function PlanBar({ label, used, resetsLabel }: { label: string; used: number; resetsLabel: string }) {
  const pct = Math.round(used * 100);
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-gray-500">{label}</span>
      <div className="w-12 h-1 rounded-full bg-[#1e1e2e] overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor(used)}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="tabular-nums text-[10px]">
        {pct}% · {resetsLabel}
      </span>
    </div>
  );
}

function barColor(fraction: number): string {
  if (fraction >= 0.9) return "bg-red-500";
  if (fraction >= 0.7) return "bg-amber-500";
  return "bg-green-500";
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function tierBadge(tier: Tier): string {
  switch (tier) {
    case "subscription": return "Subscription";
    case "metered":      return "Metered";
    case "free":         return "Free";
  }
}

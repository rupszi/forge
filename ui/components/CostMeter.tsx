"use client";

import type { BudgetState } from "@/lib/types";

interface Props {
  budget: BudgetState;
}

export function CostMeter({ budget }: Props) {
  const pct = Math.min(100, budget.percent_used);
  const barColor = pct > 80 ? "bg-red-500" : pct > 50 ? "bg-amber-500" : "bg-green-500";

  return (
    <div className="flex items-center gap-4 text-xs text-gray-400">
      <span>${budget.spent_usd.toFixed(2)} / ${budget.budget_usd.toFixed(2)}</span>
      <div className="w-24 h-1.5 rounded-full bg-[#1e1e2e] overflow-hidden">
        <div className={`h-full rounded-full ${barColor} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      {budget.exhausted && <span className="text-red-400 font-medium">Budget exhausted</span>}
    </div>
  );
}

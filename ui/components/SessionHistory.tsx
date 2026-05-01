"use client";

import type { Session } from "@/lib/types";

interface Props {
  sessions: Session[];
}

export function SessionHistory({ sessions }: Props) {
  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
      <h3 className="text-sm font-semibold text-gray-400 mb-3">Session History</h3>
      <div className="space-y-2 max-h-60 overflow-y-auto">
        {sessions.map((s) => (
          <details key={s.id} className="group">
            <summary className="flex items-center gap-2 cursor-pointer hover:bg-[#0a0a0f] rounded p-1.5">
              <span className="font-mono text-[10px] text-gray-600">{s.id}</span>
              <span className="text-xs text-gray-400 flex-1 truncate">{s.objective}</span>
              <span className="text-[10px] text-gray-600">${s.total_cost.toFixed(2)}</span>
            </summary>
            <div className="pl-4 mt-1 text-xs text-gray-500 space-y-0.5">
              <p>Sprints: {s.completed_sprints}/{s.total_sprints} completed, {s.failed_sprints} failed</p>
              <p>KB items created: {s.knowledge_items_created}, applied: {s.knowledge_items_applied}</p>
              <p>Started: {new Date(s.started_at).toLocaleString()}</p>
            </div>
          </details>
        ))}
        {sessions.length === 0 && <p className="text-xs text-gray-600 text-center py-4">No sessions yet.</p>}
      </div>
    </div>
  );
}

"use client";

import type { SprintContract } from "@/lib/types";

const MODEL_COLORS: Record<string, string> = {
  opus: "bg-purple-600 text-white",
  sonnet: "bg-purple-500/60 text-purple-100",
  haiku: "bg-purple-400/40 text-purple-200",
  ollama: "bg-teal-600 text-white",
};

interface Props {
  sprints: SprintContract[];
  onRunAll: () => void;
}

export function PlanView({ sprints, onRunAll }: Props) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide">Sprint Plan</h2>
        <button
          onClick={onRunAll}
          className="px-3 py-1 text-xs rounded bg-green-600 text-white hover:bg-green-500 transition-colors"
        >
          Run All
        </button>
      </div>
      <div className="space-y-2">
        {sprints.map((sprint) => (
          <div key={sprint.id} className="p-3 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-500">{sprint.id}</span>
                  <span className={`px-1.5 py-0.5 text-[10px] rounded font-medium ${MODEL_COLORS[sprint.assigned_model] || "bg-gray-700 text-gray-300"}`}>
                    {sprint.assigned_model}
                  </span>
                  {sprint.depends_on.length > 0 && (
                    <span className="text-[10px] text-gray-600">
                      depends: {sprint.depends_on.join(", ")}
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-gray-300">{sprint.description}</p>
              </div>
            </div>
            <details className="mt-2">
              <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-400">
                Done criteria ({sprint.done_criteria.length})
              </summary>
              <ul className="mt-1 space-y-0.5">
                {sprint.done_criteria.map((c, i) => (
                  <li key={i} className="text-xs text-gray-400 pl-3">
                    {i + 1}. {c}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        ))}
      </div>
    </div>
  );
}

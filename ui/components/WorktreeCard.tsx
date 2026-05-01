"use client";

import type { SprintContract } from "@/lib/types";

const STATUS_STYLES: Record<string, { dot: string; bg: string }> = {
  pending: { dot: "bg-gray-500", bg: "border-gray-800/30" },
  started: { dot: "bg-blue-500 animate-pulse-dot", bg: "border-blue-800/30" },
  generated: { dot: "bg-purple-500", bg: "border-purple-800/30" },
  evaluated: { dot: "bg-amber-500", bg: "border-amber-800/30" },
  completed: { dot: "bg-green-500", bg: "border-green-800/30" },
  failed: { dot: "bg-red-500", bg: "border-red-800/30" },
  revised: { dot: "bg-amber-400 animate-pulse-dot", bg: "border-amber-800/30" },
};

interface Props {
  sprint: SprintContract;
}

export function WorktreeCard({ sprint }: Props) {
  const style = STATUS_STYLES[sprint.status] || STATUS_STYLES.pending;

  return (
    <div className={`p-3 rounded-lg bg-[#12121a] border ${style.bg}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-2 h-2 rounded-full ${style.dot}`} />
        <span className="font-mono text-xs text-gray-500">{sprint.id}</span>
        <span className="text-xs text-gray-600 ml-auto">{sprint.status}</span>
      </div>
      <p className="text-sm text-gray-300 line-clamp-2">{sprint.description}</p>
      {sprint.revision_count > 0 && (
        <p className="mt-1 text-xs text-amber-400">Revision {sprint.revision_count}</p>
      )}
      {sprint.error && (
        <p className="mt-1 text-xs text-red-400 line-clamp-2">{sprint.error}</p>
      )}
    </div>
  );
}

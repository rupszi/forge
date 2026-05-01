"use client";

import type { SprintContract } from "@/lib/types";
import { WorktreeCard } from "./WorktreeCard";

interface Props {
  sprints: SprintContract[];
}

export function TaskDashboard({ sprints }: Props) {
  const sorted = [...sprints].sort((a, b) => {
    const order: Record<string, number> = { started: 0, generated: 1, evaluated: 2, pending: 3, completed: 4, failed: 5 };
    return (order[a.status] ?? 3) - (order[b.status] ?? 3);
  });

  return (
    <div className="mt-4 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {sorted.map((sprint) => (
        <WorktreeCard key={sprint.id} sprint={sprint} />
      ))}
    </div>
  );
}

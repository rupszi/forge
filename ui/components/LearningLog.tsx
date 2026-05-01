"use client";

interface LearningStats {
  gotchas_learned: number;
  patterns_updated: number;
  research_insights: number;
}

interface Props {
  stats: LearningStats | null;
}

export function LearningLog({ stats }: Props) {
  if (!stats) return null;

  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-teal-800/30">
      <h3 className="text-sm font-semibold text-gray-400 mb-2">Session Learnings</h3>
      <p className="text-xs text-gray-400">
        {stats.gotchas_learned} gotchas learned, {stats.patterns_updated} patterns updated, {stats.research_insights} research insights cached
      </p>
    </div>
  );
}

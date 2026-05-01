"use client";

import type { ReviewResult } from "@/lib/types";

interface Props {
  result: ReviewResult;
}

const VERDICT_STYLES: Record<string, string> = {
  PASS: "bg-green-900/40 text-green-400",
  FAIL: "bg-red-900/40 text-red-400",
  ERROR: "bg-gray-800 text-gray-400",
};

export function ReviewPanel({ result }: Props) {
  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-400">Review Panel</h3>
        <span className={`px-2 py-0.5 text-xs rounded font-medium ${VERDICT_STYLES[result.overall_verdict] || VERDICT_STYLES.ERROR}`}>
          {result.overall_verdict}
        </span>
      </div>

      {result.critical_issues.length > 0 && (
        <div className="mb-3 p-2 rounded bg-red-900/10 border border-red-800/20">
          <p className="text-xs font-medium text-red-400 mb-1">Critical Issues (flagged by 2+ reviewers)</p>
          {result.critical_issues.map((issue, i) => (
            <p key={i} className="text-xs text-red-300">- {issue}</p>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {result.perspectives.map((p) => (
          <details key={p.name} className="group">
            <summary className="flex items-center gap-2 cursor-pointer hover:bg-[#0a0a0f] rounded p-1">
              <span className={`px-1.5 py-0.5 text-[10px] rounded ${VERDICT_STYLES[p.verdict] || VERDICT_STYLES.ERROR}`}>
                {p.verdict}
              </span>
              <span className="text-xs text-gray-400">{p.name}</span>
              <span className="text-[10px] text-gray-600 ml-auto">{p.model}</span>
            </summary>
            <div className="pl-4 mt-1 space-y-0.5">
              {p.issues.map((issue, i) => (
                <p key={i} className="text-xs text-gray-400">Issue: {issue}</p>
              ))}
              {p.suggestions.map((s, i) => (
                <p key={i} className="text-xs text-teal-400">Fix: {s}</p>
              ))}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

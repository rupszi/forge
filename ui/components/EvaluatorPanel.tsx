"use client";

import type { EvaluatorResult } from "@/lib/types";

interface Props {
  result: EvaluatorResult;
}

export function EvaluatorPanel({ result }: Props) {
  return (
    <div className="p-4 rounded-lg bg-[#12121a] border border-[#1e1e2e]">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-sm font-semibold text-gray-400">Evaluator</h3>
        <span className={`px-2 py-0.5 text-xs rounded font-medium ${
          result.verdict === "APPROVED" ? "bg-green-900/40 text-green-400" : "bg-amber-900/40 text-amber-400"
        }`}>
          {result.verdict}
        </span>
      </div>
      <ul className="space-y-1.5">
        {result.criteria_results.map((cr, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <span className={cr.passed ? "text-green-500" : "text-red-500"}>
              {cr.passed ? "PASS" : "FAIL"}
            </span>
            <span className="text-gray-400">{cr.criterion}</span>
            {cr.evidence && <span className="text-gray-600">- {cr.evidence}</span>}
            {cr.fix_needed && <span className="text-amber-400">- {cr.fix_needed}</span>}
          </li>
        ))}
      </ul>
      {result.feedback && (
        <div className="mt-3 p-2 rounded bg-[#0a0a0f] text-xs text-gray-400 whitespace-pre-wrap">
          {result.feedback}
        </div>
      )}
    </div>
  );
}

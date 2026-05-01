/**
 * OutputStream — the live process-progression panel.
 *
 * Renders a scrolling, color-coded transcript of every event flowing
 * through the WebSocket. Replaces the static TaskDashboard for power
 * users who want the full chronology rather than a card grid.
 *
 * Maps trace.jsonl event types to UI affordances:
 *
 *   session.start              "── Session sess-abc started ──"      gray header
 *   plan.created               "Plan: 4 sprints"                      blue
 *   wave.start                 "Wave 1 — sprint-1, sprint-2"         dim
 *   worktree.created           "Worktree: .forge/worktrees/sprint-1"  dim
 *   sprint.attempt             "Sprint sprint-1 — attempt 1"          purple
 *   sprint.evaluated           "  → REVISE: criterion 3 missing"      amber|green
 *   sprint.approved            "  ✓ approved"                         green
 *   sprint.revising            "  ↻ revising (round 2)"               amber
 *   sprint.recovered           "  ✓ recovered via ADaPT"              teal
 *   sprint.crashed             "  ✗ crashed: <error>"                 red
 *   recovery.adapt.start       "Recovery: ADaPT decomposition started" coral
 *   recovery.adapt.decomposed  "  ↳ split into 3 sub-sprints"         coral
 *   recovery.consistency.*     "Self-consistency: attempt N/3"        coral
 *   budget.downgrade           "Budget: opus → sonnet for sprint-2"   amber
 *   budget.exhausted           "Budget exhausted — sprint failed"     red
 *
 * Filters via the TranscriptView verbosity:
 *   normal    → sprint.* + recovery.* + budget.*
 *   thinking  → + reasoning blocks (when generator emits them)
 *   verbose   → everything (every wave.start, worktree.created, etc.)
 *   summary   → only sprint.approved / sprint.crashed / session.complete
 */

import React, { useEffect, useRef } from "react";
import type { Verbosity } from "./TranscriptView";

export type StreamEvent = {
  ts: string;                // ISO 8601
  session_id: string;
  type: string;              // EventType.value
  sprint_id?: string;
  data?: Record<string, any>;
};

export type OutputStreamProps = {
  events: StreamEvent[];
  verbosity: Verbosity;
};

export function OutputStream({ events, verbosity }: OutputStreamProps) {
  const filtered = events.filter((e) => isVisible(e, verbosity));
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [filtered.length]);

  return (
    <div className="rounded-lg bg-[#0a0a0f] border border-[#1e1e2e] font-mono text-[12px] overflow-hidden">
      <div className="px-3 py-2 border-b border-[#1e1e2e] flex items-center justify-between bg-[#0d0d12]">
        <span className="text-xs text-gray-400">Output</span>
        <div className="flex items-center gap-2 text-[10px] text-gray-600">
          <span>{filtered.length} events</span>
          <span>·</span>
          <span className="capitalize">{verbosity}</span>
        </div>
      </div>
      <div className="max-h-[60vh] overflow-y-auto px-3 py-2 space-y-0.5">
        {filtered.length === 0 ? (
          <div className="text-center text-gray-600 py-8 text-xs">
            No events yet. Submit a prompt to start.
          </div>
        ) : (
          filtered.map((e, i) => <Line key={i} event={e} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function Line({ event }: { event: StreamEvent }) {
  const t = event.ts.slice(11, 19);  // HH:MM:SS
  const colorClass = colorFor(event.type);
  const summary = summarize(event);

  return (
    <div className={`leading-snug ${colorClass}`}>
      <span className="text-gray-700 mr-2">{t}</span>
      <span className="text-gray-600 mr-2">{event.type}</span>
      {event.sprint_id && (
        <span className="text-purple-500 mr-2">[{shortId(event.sprint_id)}]</span>
      )}
      {summary}
    </div>
  );
}

function shortId(id: string): string {
  // sprint-a1b2c3d4-... → a1b2c3d4
  const parts = id.split("-");
  if (parts.length >= 2) return parts[1].slice(0, 6);
  return id.slice(0, 8);
}

function colorFor(type: string): string {
  if (type.startsWith("sprint.approved") || type === "sprint.recovered") return "text-green-400";
  if (type.startsWith("sprint.crashed") || type === "budget.exhausted") return "text-red-400";
  if (type.startsWith("sprint.revising") || type.startsWith("budget.downgrade")) return "text-amber-300";
  if (type.startsWith("recovery.")) return "text-orange-400";
  if (type.startsWith("plan.") || type.startsWith("session.start")) return "text-blue-300";
  if (type.startsWith("sprint.")) return "text-purple-300";
  return "text-gray-500";
}

function summarize(e: StreamEvent): string {
  const d = e.data ?? {};
  switch (e.type) {
    case "session.start":
      return `objective: ${d.objective ?? ""}`;
    case "session.complete":
      return `done — ${d.completed ?? 0} ok, ${d.failed ?? 0} failed, $${(d.total_cost ?? 0).toFixed(4)}`;
    case "plan.created":
      return `${d.sprint_count ?? "?"} sprint(s)`;
    case "wave.start":
      return `wave ${d.wave ?? "?"} — ${d.sprint_count ?? "?"} sprint(s)`;
    case "wave.complete":
      return `wave done — spent $${(d.spent_usd ?? 0).toFixed(4)}`;
    case "worktree.created":
      return `path: ${d.path ?? ""}`;
    case "sprint.attempt":
      return `attempt ${d.attempt ?? "?"}`;
    case "sprint.evaluated":
      return `verdict: ${d.verdict ?? "?"} (in=${d.tokens_in ?? 0} out=${d.tokens_out ?? 0})`;
    case "sprint.approved":
      return `✓`;
    case "sprint.revising":
      return `revision ${d.revision ?? "?"} — ${truncate(d.feedback ?? "", 80)}`;
    case "sprint.recovered":
      return `✓ recovered via ${d.sub_count ?? "?"} sub-sprints`;
    case "sprint.crashed":
      return `✗ ${d.error ?? "unknown"}`;
    case "recovery.adapt.start":
      return `decomposing…`;
    case "recovery.adapt.decomposed":
      return `→ ${d.sub_sprint_count ?? "?"} sub-sprints`;
    case "recovery.adapt.subsprint_passed":
      return `  ✓ ${d.criterion ?? ""}`;
    case "recovery.adapt.subsprint_failed":
      return `  ✗ ${truncate(d.feedback ?? "", 60)}`;
    case "budget.downgrade":
      return `${d.sprint_id ?? ""} → ${d.new_model ?? "?"}`;
    case "budget.exhausted":
      return `model: ${d.model ?? "?"}`;
    case "repomap.built":
      return `${d.size ?? 0} bytes`;
    default:
      // For unknown event types, dump the data dict compactly
      return Object.keys(d).length === 0 ? "" : truncate(JSON.stringify(d), 100);
  }
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}

function isVisible(e: StreamEvent, v: Verbosity): boolean {
  if (v === "verbose") return true;
  if (v === "summary") {
    return ["sprint.approved", "sprint.crashed", "sprint.recovered", "session.complete"].includes(
      e.type
    );
  }
  if (v === "thinking") {
    if (e.type === "generator.thinking") return true;
  }
  // normal
  return (
    e.type.startsWith("sprint.") ||
    e.type.startsWith("recovery.") ||
    e.type.startsWith("budget.") ||
    e.type === "plan.created" ||
    e.type === "session.start" ||
    e.type === "session.complete"
  );
}

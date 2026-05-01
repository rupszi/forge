"use client";

import { useForgeSocket } from "@/hooks/useForgeSocket";
import { PromptInput } from "@/components/PromptInput";
import { PlanView } from "@/components/PlanView";
import { TaskDashboard } from "@/components/TaskDashboard";
import { CostMeter } from "@/components/CostMeter";
import { MemoryBrowser } from "@/components/MemoryBrowser";
import { SessionHistory } from "@/components/SessionHistory";

export default function Home() {
  const { connected, context, sprints, budget, knowledge, sessions, errors, send } = useForgeSocket();

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-white">Forge</h1>
          <span className={`w-2 h-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"} animate-pulse-dot`} />
          <span className="text-xs text-gray-500">{connected ? "Connected" : "Disconnected"}</span>
        </div>
        <CostMeter budget={budget} />
      </div>

      {/* Context badges */}
      {context && (
        <div className="flex flex-wrap gap-2 mb-4">
          {context.framework && (
            <span className="px-2 py-0.5 text-xs rounded bg-purple-900/40 text-purple-300 border border-purple-800/30">
              {context.framework}
            </span>
          )}
          {context.language && (
            <span className="px-2 py-0.5 text-xs rounded bg-blue-900/40 text-blue-300 border border-blue-800/30">
              {context.language}
            </span>
          )}
          {context.mcp_servers?.map((s) => (
            <span key={s.name} className="px-2 py-0.5 text-xs rounded bg-teal-900/40 text-teal-300 border border-teal-800/30">
              {s.name}
            </span>
          ))}
          {context.knowledge_count !== undefined && context.knowledge_count > 0 && (
            <span className="px-2 py-0.5 text-xs rounded bg-amber-900/40 text-amber-300 border border-amber-800/30">
              {context.knowledge_count} KB items
            </span>
          )}
        </div>
      )}

      {/* Prompt input */}
      <PromptInput onSubmit={(obj) => send({ type: "plan", objective: obj })} disabled={!connected} />

      {/* Errors */}
      {errors.length > 0 && (
        <div className="mt-4 p-3 rounded bg-red-900/20 border border-red-800/30">
          {errors.map((e, i) => (
            <p key={i} className="text-sm text-red-400">{e}</p>
          ))}
        </div>
      )}

      {/* Plan + Tasks */}
      {sprints.length > 0 && (
        <div className="mt-6">
          <PlanView sprints={sprints} onRunAll={() => send({ type: "run_all" })} />
          <TaskDashboard sprints={sprints} />
        </div>
      )}

      {/* Bottom panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
        <MemoryBrowser
          items={knowledge}
          onSearch={(q) => send({ type: "search_knowledge", query: q })}
          onAdd={(cat, topic, content) => send({ type: "add_knowledge", category: cat, topic, content })}
          onDelete={(id) => send({ type: "delete_knowledge", item_id: id })}
        />
        <SessionHistory sessions={sessions} />
      </div>
    </main>
  );
}

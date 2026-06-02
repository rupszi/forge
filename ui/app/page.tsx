"use client";

import { useState } from "react";

import { useForgeSocket } from "@/hooks/useForgeSocket";
import { PromptInput } from "@/components/PromptInput";
import { PlanView } from "@/components/PlanView";
import { TaskDashboard } from "@/components/TaskDashboard";
import { MemoryBrowser } from "@/components/MemoryBrowser";
import { SessionHistory } from "@/components/SessionHistory";

// Claude-Code-style additions (this sprint):
import { ContextMeter } from "@/components/ContextMeter";
import { ModePicker } from "@/components/ModePicker";
import { TranscriptView } from "@/components/TranscriptView";
import { AttachMenu } from "@/components/AttachMenu";
import { SlashCommandPalette, buildDefaultCommands } from "@/components/SlashCommandPalette";
import { OutputStream } from "@/components/OutputStream";
import { MetadataBar } from "@/components/MetadataBar";
import { LocalityIndicator } from "@/components/LocalityIndicator";
import { PoolMeter } from "@/components/PoolMeter";
import { ProjectBar } from "@/components/ProjectBar";

export default function Home() {
  const {
    connected,
    context,
    sprints,
    budget,
    knowledge,
    sessions,
    errors,
    send,
    mode,
    setMode,
    verbosity,
    setVerbosity,
    model,
    contextUsed,
    contextCap,
    streamEvents,
    enabledConnectors,
    durationSec,
    totalTokens,
    diffStats,
    tier,
    locality,
    pool,
    installedModels,
    setActiveModel,
    folderPath,
    folderIsGit,
    branches,
    currentBranch,
    connectFolder,
    selectBranch,
    initFolder,
  } = useForgeSocket();

  // Slash palette state — controlled here so the prompt input can trigger it
  const [slashOpen, setSlashOpen] = useState(false);
  const [slashQuery, setSlashQuery] = useState("");
  const slashCommands = buildDefaultCommands(send);

  return (
    <main className="max-w-7xl mx-auto px-4 py-6">
      {/* ── Header strip: connection + context+budget meter ── */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-white">Forge</h1>
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-500" : "bg-red-500"
            } animate-pulse-dot`}
          />
          <span className="text-xs text-gray-500">
            {connected ? "Connected" : "Disconnected"}
          </span>
          <LocalityIndicator locality={locality} />
          <PoolMeter pool={pool} />
        </div>
        <ContextMeter
          contextUsed={contextUsed}
          contextCap={contextCap}
          costUsd={budget.spent_usd}
          budgetUsd={budget.budget_usd}
          model={model}
          installedModels={installedModels}
          onModelChange={setActiveModel}
          tier={tier}
        />
      </div>

      {/* ── Connect a folder + pick a branch ── */}
      <ProjectBar
        folderPath={folderPath}
        folderIsGit={folderIsGit}
        branches={branches}
        currentBranch={currentBranch}
        onConnect={connectFolder}
        onSelectBranch={selectBranch}
        onInit={initFolder}
      />

      {/* ── Stack badges (framework / language / MCP servers / KB count) ── */}
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
            <span
              key={s.name}
              className="px-2 py-0.5 text-xs rounded bg-teal-900/40 text-teal-300 border border-teal-800/30"
            >
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

      {/* ── Metadata bar (Claude-Code style: duration · tokens · branch · diff · PR) ── */}
      <div className="mb-3">
        <MetadataBar
          durationSec={durationSec}
          totalTokens={totalTokens}
          branch={(context as any)?.default_branch ?? undefined}
          worktreeCount={sprints.filter((s) => (s as any).assigned_worktree).length}
          diffAdded={diffStats.added}
          diffRemoved={diffStats.removed}
          prAvailable={
            sprints.length > 0 &&
            sprints.every((s) => s.status === "completed") &&
            !!(context as any)?.remote_url
          }
          onCreatePR={() => send({ type: "pr.create" })}
        />
      </div>

      {/* ── Prompt input (with relative positioning for the slash palette) ── */}
      <div className="relative">
        <PromptInput
          onSubmit={(obj) => {
            if (obj.startsWith("/")) {
              const text = obj.slice(1).trim();
              const cmdName = text.split(" ")[0];
              const args = text.split(" ").slice(1).join(" ");
              const cmd = slashCommands.find((c) => c.name === cmdName);
              if (cmd) cmd.handler(args);
              return;
            }
            send({ type: "plan", objective: obj });
          }}
          onChange={(text) => {
            if (text.startsWith("/")) {
              setSlashOpen(true);
              setSlashQuery(text.slice(1));
            } else if (slashOpen) {
              setSlashOpen(false);
            }
          }}
          disabled={!connected}
        />

        <SlashCommandPalette
          open={slashOpen}
          query={slashQuery}
          onClose={() => setSlashOpen(false)}
          onSelect={(cmd, args) => {
            cmd.handler(args);
            setSlashOpen(false);
            setSlashQuery("");
          }}
          commands={slashCommands}
        />

        {/* ── Bottom action row: AttachMenu + ModePicker + TranscriptView ── */}
        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <AttachMenu
              enabledConnectors={enabledConnectors}
              onAction={(a) => {
                switch (a.type) {
                  case "files":
                    send({ type: "attach.files", names: a.files.map((f) => f.name) });
                    break;
                  case "folder":
                    send({ type: "attach.folder" });
                    break;
                  case "slash":
                    setSlashOpen(true);
                    setSlashQuery("");
                    break;
                  case "connector":
                    send({ type: "connector.activate", name: a.name });
                    break;
                  case "plugins":
                    send({ type: "plugins.gallery" });
                    break;
                }
              }}
            />
            <ModePicker current={mode} onChange={setMode} />
          </div>
          <TranscriptView current={verbosity} onChange={setVerbosity} />
        </div>
      </div>

      {/* ── Errors ── */}
      {errors.length > 0 && (
        <div className="mt-4 p-3 rounded bg-red-900/20 border border-red-800/30">
          {errors.map((e, i) => (
            <p key={i} className="text-sm text-red-400">
              {e}
            </p>
          ))}
        </div>
      )}

      {/* ── Plan + Tasks ── */}
      {sprints.length > 0 && (
        <div className="mt-6">
          <PlanView sprints={sprints} onRunAll={() => send({ type: "run_all" })} />
          <TaskDashboard sprints={sprints} />
        </div>
      )}

      {/* ── Live process-progression OUTPUT stream ── */}
      <div className="mt-6">
        <OutputStream events={streamEvents} verbosity={verbosity} />
      </div>

      {/* ── Bottom panels: KB browser + session history ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-8">
        <MemoryBrowser
          items={knowledge}
          onSearch={(q) => send({ type: "search_knowledge", query: q })}
          onAdd={(cat, topic, content) =>
            send({ type: "add_knowledge", category: cat, topic, content })
          }
          onDelete={(id) => send({ type: "delete_knowledge", item_id: id })}
        />
        <SessionHistory sessions={sessions} />
      </div>
    </main>
  );
}

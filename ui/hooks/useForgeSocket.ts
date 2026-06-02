"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type {
  SprintContract,
  BudgetState,
  ProjectContext,
  KnowledgeItem,
  Session,
  WSMessage,
  LocalityState,
  PoolState,
} from "@/lib/types";
import type { Mode } from "@/components/ModePicker";
import type { Verbosity } from "@/components/TranscriptView";
import type { StreamEvent } from "@/components/OutputStream";
import type { Tier } from "@/components/ContextMeter";

const WS_URL = "ws://127.0.0.1:9111";

const MAX_EVENTS = 500;     // ring buffer cap for the OutputStream
const MAX_ERRORS = 10;       // how many recent errors to keep

export function useForgeSocket() {
  const [connected, setConnected] = useState(false);
  const [context, setContext] = useState<ProjectContext | null>(null);
  const [sprints, setSprints] = useState<SprintContract[]>([]);
  const [budget, setBudget] = useState<BudgetState>({
    budget_usd: 5, spent_usd: 0, remaining_usd: 5, percent_used: 0, exhausted: false,
  });
  const [knowledge, setKnowledge] = useState<KnowledgeItem[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [errors, setErrors] = useState<string[]>([]);

  // New state added with the Claude-Code-style UI:
  const [mode, setModeState] = useState<Mode>("auto");
  const [verbosity, setVerbosityState] = useState<Verbosity>("normal");
  const [model, setModel] = useState<string>("qwen3-coder-next");
  const [tier, setTier] = useState<Tier>("free");  // daemon-supplied; see daemon/billing.py
  const [contextUsed, setContextUsed] = useState(0);
  const [contextCap, setContextCap] = useState(128_000);
  const [streamEvents, setStreamEvents] = useState<StreamEvent[]>([]);
  const [enabledConnectors, setEnabledConnectors] = useState<string[]>([]);
  const [sessionStartTs, setSessionStartTs] = useState<number>(Date.now());
  const [totalTokens, setTotalTokens] = useState(0);
  const [diffStats, setDiffStats] = useState({ added: 0, removed: 0 });
  const [locality, setLocality] = useState<LocalityState>({
    mode: "local",
    cloud_enabled: false,
  });
  const [pool, setPool] = useState<PoolState | null>(null);

  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setSessionStartTs(Date.now());
      ws.send(JSON.stringify({ type: "init", path: "." }));
      // Pull the local-first locality + model-pool state up front so the
      // indicators render immediately (they also arrive as pushes later).
      ws.send(JSON.stringify({ type: "locality" }));
      ws.send(JSON.stringify({ type: "pool" }));
    };

    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (event) => {
      const raw = event.data as string;
      const msg = JSON.parse(raw) as WSMessage & { ts?: string };
      const isStreamEvent =
        typeof msg.type === "string" &&
        (msg.type.startsWith("sprint.") ||
          msg.type.startsWith("recovery.") ||
          msg.type.startsWith("budget.") ||
          msg.type.startsWith("plan.") ||
          msg.type.startsWith("session.") ||
          msg.type.startsWith("wave.") ||
          msg.type.startsWith("worktree.") ||
          msg.type.startsWith("repomap."));

      // Append to stream buffer (ring-buffered to MAX_EVENTS)
      if (isStreamEvent) {
        setStreamEvents((prev) => {
          const next = [
            ...prev,
            {
              ts: msg.ts ?? new Date().toISOString(),
              session_id: (msg as any).session_id ?? "",
              type: msg.type,
              sprint_id: (msg as any).sprint_id,
              data: (msg as any).data ?? msg,
            } as StreamEvent,
          ];
          return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
        });
      }

      // Per-type state updates
      switch (msg.type) {
        case "project_context": {
          const ctx = msg as unknown as ProjectContext & {
            mcp_servers?: { name: string }[];
            billing_tier?: Tier;
          };
          setContext(ctx);
          if (ctx.mcp_servers) {
            setEnabledConnectors(ctx.mcp_servers.map((s) => s.name));
          }
          if (ctx.billing_tier) {
            setTier(ctx.billing_tier);
          }
          if ((ctx as any).locality) {
            setLocality((ctx as any).locality as LocalityState);
          }
          break;
        }
        case "locality":
          setLocality(msg as unknown as LocalityState);
          break;
        case "pool_state":
          setPool(msg as unknown as PoolState);
          break;
        case "tier_changed":
          setTier((msg as any).tier as Tier);
          break;
        case "plan_created":
          setSprints((msg as any).sprints ?? []);
          break;
        case "sprint_evaluated":
        case "sprint_started":
        case "sprint_generated":
        case "sprint_revised":
          setSprints((prev) =>
            prev.map((s) =>
              s.id === (msg as any).sprint_id
                ? { ...s, status: (msg.type as string).replace("sprint_", "") }
                : s
            )
          );
          break;
        case "sprint.evaluated": {
          // EventType-style; updates token + cost meters
          const data = (msg as any).data ?? msg;
          if (typeof data.tokens_in === "number" || typeof data.tokens_out === "number") {
            setTotalTokens((t) => t + (data.tokens_in ?? 0) + (data.tokens_out ?? 0));
          }
          break;
        }
        case "budget_update":
          setBudget(msg as unknown as BudgetState);
          break;
        case "knowledge_results":
          setKnowledge((msg as any).items);
          break;
        case "status":
          setSessions((msg as any).sessions);
          setBudget((msg as any).budget);
          break;
        case "session_complete":
          setSessions((prev) => [(msg as any).session, ...prev]);
          break;
        case "diff_stats":
          setDiffStats({ added: (msg as any).added, removed: (msg as any).removed });
          break;
        case "model_changed":
          setModel((msg as any).model);
          if ((msg as any).context_window) setContextCap((msg as any).context_window);
          break;
        case "context_used":
          setContextUsed((msg as any).tokens);
          break;
        case "mode_changed":
          setModeState((msg as any).mode as Mode);
          break;
        case "connectors_list":
          setEnabledConnectors((msg as any).names ?? []);
          break;
        case "error":
          setErrors((prev) => [...prev.slice(-(MAX_ERRORS - 1)), (msg as any).error]);
          break;
      }
    };

    return () => ws.close();
  }, []);

  const send = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  // Convenience setters that also notify the daemon
  const setMode = useCallback((m: Mode) => {
    setModeState(m);
    send({ type: "set_mode", mode: m });
  }, [send]);

  const setVerbosity = useCallback((v: Verbosity) => {
    setVerbosityState(v);
    // verbosity is client-side only; no daemon notification needed
  }, []);

  const durationSec = Math.floor((Date.now() - sessionStartTs) / 1000);

  return {
    connected,
    context,
    sprints,
    budget,
    knowledge,
    sessions,
    errors,
    send,
    // new
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
    locality,
    pool,
    tier,
  };
}

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import type { SprintContract, BudgetState, ProjectContext, KnowledgeItem, Session, WSMessage } from "@/lib/types";

const WS_URL = "ws://127.0.0.1:9111";

export function useForgeSocket() {
  const [connected, setConnected] = useState(false);
  const [context, setContext] = useState<ProjectContext | null>(null);
  const [sprints, setSprints] = useState<SprintContract[]>([]);
  const [budget, setBudget] = useState<BudgetState>({ budget_usd: 5, spent_usd: 0, remaining_usd: 5, percent_used: 0, exhausted: false });
  const [knowledge, setKnowledge] = useState<KnowledgeItem[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: "init", path: "." }));
    };

    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as WSMessage;
      switch (msg.type) {
        case "project_context":
          setContext(msg as unknown as ProjectContext);
          break;
        case "plan_created":
          setSprints(msg.sprints);
          break;
        case "sprint_evaluated":
        case "sprint_started":
        case "sprint_generated":
        case "sprint_revised":
          setSprints((prev) =>
            prev.map((s) => s.id === msg.sprint_id ? { ...s, status: msg.type.replace("sprint_", "") } : s)
          );
          break;
        case "budget_update":
          setBudget(msg as unknown as BudgetState);
          break;
        case "knowledge_results":
          setKnowledge(msg.items);
          break;
        case "status":
          setSessions(msg.sessions);
          setBudget(msg.budget);
          break;
        case "session_complete":
          setSessions((prev) => [msg.session, ...prev]);
          break;
        case "error":
          setErrors((prev) => [...prev.slice(-9), msg.error]);
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

  return { connected, context, sprints, budget, knowledge, sessions, errors, send };
}

export interface SprintContract {
  id: string;
  session_id: string;
  description: string;
  done_criteria: string[];
  depends_on: string[];
  files_scope: string[];
  assigned_model: string;
  assigned_worktree: string | null;
  status: string;
  revision_count: number;
  error: string | null;
  estimated_tokens: number;
  critical: boolean;
  created_at: string;
}

export interface Session {
  id: string;
  project_path: string;
  objective: string;
  detected_stack: Record<string, unknown> | null;
  started_at: string;
  ended_at: string | null;
  total_sprints: number;
  completed_sprints: number;
  failed_sprints: number;
  total_cost: number;
  knowledge_items_created: number;
  knowledge_items_applied: number;
}

export interface KnowledgeItem {
  id: number;
  category: string;
  topic: string;
  content: string;
  source: string;
  confidence: number;
  times_applied: number;
  times_helpful: number;
  created_at: string;
  last_used_at: string;
}

export interface CriterionResult {
  criterion: string;
  passed: boolean;
  evidence: string;
  fix_needed: string;
}

export interface EvaluatorResult {
  verdict: string;
  criteria_results: CriterionResult[];
  feedback: string;
}

export interface ReviewPerspective {
  name: string;
  model: string;
  verdict: string;
  issues: string[];
  suggestions: string[];
}

export interface ReviewResult {
  overall_verdict: string;
  perspectives: ReviewPerspective[];
  critical_issues: string[];
  action_items: string[];
}

export interface BudgetState {
  budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
  percent_used: number;
  exhausted: boolean;
}

// Local-first locality indicator (daemon is the source of truth; see
// daemon/locality.py). "local" = zero outbound inference; "cloud" = the user
// explicitly opted in via FORGE_CLOUD_ENABLED.
export interface LocalityState {
  mode: "local" | "cloud";
  cloud_enabled: boolean;
}

// Model pool state for the live RAM meter (daemon/pool.py).
export interface PoolModel {
  name: string;
  size_gb: number;
  pinned: boolean;
  in_use: number;
}

export interface PoolState {
  budget_gb: number;
  resident_gb: number;
  models: PoolModel[];
}

// Context-window (num_ctx) sizing for the dropdown (daemon/context_window.py).
export interface ContextPreset {
  tokens: number;
  label: string;
  fits: boolean; // within the RAM-safe ceiling
  exceeds_model: boolean; // above the model's trained max
  kv_gb: number; // approx KV-cache cost
}

export interface ContextOptions {
  presets: ContextPreset[];
  auto: number; // tokens "auto" resolves to
  model_max: number;
  ceiling: number; // RAM-safe ceiling
  setting: number | "auto";
  kv_cache_type: string; // f16 | q8_0 | q4_0
  kv_cache_types: string[];
  model?: string;
}

export interface ProjectContext {
  path: string;
  is_git: boolean;
  default_branch: string;
  remote_url: string;
  language: string;
  framework: string;
  package_manager: string;
  has_claude: boolean;
  mcp_servers: { name: string; command: string | null; args: string[] }[];
  claude_rules_count: number;
  auto_memory_count: number;
  available_tools: Record<string, boolean>;
  knowledge_count?: number;
}

// Wide-open message envelope. The dashboard handles many event types
// (EventType.value strings like "sprint.evaluated") plus the legacy
// snake_case ones — pinning every type here is a maintenance cost we
// don't pay back. The hook narrows by inspection.
export type WSMessage = {
  type: string;
  [key: string]: unknown;
};

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

export type WSMessage =
  | { type: "project_context" } & ProjectContext
  | { type: "plan_created"; sprints: SprintContract[] }
  | { type: "sprint_started"; sprint_id: string; attempt: number }
  | { type: "sprint_generated"; sprint_id: string }
  | { type: "sprint_evaluated"; sprint_id: string; verdict: string }
  | { type: "sprint_revised"; sprint_id: string; revision: number }
  | { type: "sprint_completed"; sprint_id: string }
  | { type: "sprint_failed"; sprint_id: string; error: string }
  | { type: "merge_ready"; worktrees: string[] }
  | { type: "merge_complete" }
  | { type: "budget_update" } & BudgetState
  | { type: "budget_downgrade"; sprint_id: string; model: string }
  | { type: "knowledge_results"; items: KnowledgeItem[] }
  | { type: "knowledge_updated"; id?: number; deleted?: boolean }
  | { type: "session_complete"; session: Session }
  | { type: "status"; sessions: Session[]; knowledge_count: number; budget: BudgetState }
  | { type: "error"; error: string };

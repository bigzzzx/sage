/**
 * 后端 API 封装 (v3 - 三层 Track/Service/Capability)。
 */
import { getStoredUser, getToken } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function authenticatedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  return fetch(url, {
    ...init,
    headers: { ...Object.fromEntries(new Headers(init.headers).entries()), Authorization: `Bearer ${token || ""}` },
  });
}

async function apiError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(typeof body?.detail === "string" ? body.detail : `${fallback} (${response.status})`);
}

// ---------- 题目类型 ----------

export type Question =
  | {
      id: string;
      type: "choice";
      dimension_id: string; // capability_id
      difficulty?: string;
      question: string;
      options: string[];
      correct_answer?: string;
      explanation?: string;
      source_refs?: { id: string; url: string; fact: string }[];
      mapping_warning?: string;
    }
  | {
      id: string;
      type: "open";
      dimension_id: string;
      difficulty?: string;
      question: string;
      scoring_rubric?: string[];
      reference_answer?: string;
      source_refs?: { id: string; url: string; fact: string }[];
      mapping_warning?: string;
    };

// ---------- Taxonomy 类型 ----------

export interface CapabilityDef {
  id: string;
  name: string;
  description: string;
  levels: { L1: string; L2: string; L3: string };
}

export interface ServiceDef {
  id: string;
  name: string;
  icon?: string;
  is_real?: boolean;
  summary?: string;
  capabilities?: CapabilityDef[];
}

export interface TrackDef {
  id: string;
  name: string;
  icon?: string;
  description?: string;
  services: ServiceDef[];
}

export interface FullTaxonomy {
  version: string;
  tracks: TrackDef[];
}

// ---------- 测评结果类型 ----------

export interface AnswerItem {
  question_id: string;
  answer: string;
}

export interface CapabilityScore {
  service_id: string;
  service_name: string;
  capability_id: string;
  capability_name: string;
  score: number;
  sample_count: number;
}

export interface RadarItem {
  dimension_id: string;
  dimension_name: string;
  score: number;
}

export interface ScoreDetail {
  accuracy: number;
  completeness: number;
  diagnostic_approach: number;
  depth: number;
  practicality: number;
}

export interface QuestionResult {
  question_id: string;
  type: "choice" | "open";
  is_correct?: boolean | null;
  score_detail?: ScoreDetail | null;
  total_score: number;
  level: string;
  feedback: string;
  scoring_version?: string;
}

export interface LearningResource {
  title: string;
  url: string;
  type: string; // doc / video / lab
}

export interface ConceptPoint {
  point: string;
  search_query?: string;
  url: string; // 后端拼好的搜索 URL
}

export interface LearningTask {
  day: string;
  topic: string;
  task_type: string; // reading | video | lab | review | quiz
  targets_gap_ids?: string[]; // 本 task 直击的盲区 id
  objective?: string;
  deliverable?: string; // 预期产出物
  concepts?: ConceptPoint[];
  hands_on?: string;
  preconditions?: string;
  verification_steps?: string;
  risk_and_cleanup?: string;
  hands_on_search?: string;
  hands_on_url?: string;
  troubleshooting?: string;
  description?: string; // 兼容旧字段
  resources?: LearningResource[]; // 兼容旧字段
  time_minutes: number;
}

export interface WeekPlan {
  week: number;
  focus: string;
  tasks: LearningTask[];
}

export interface LearningPlan {
  plan_name: string;
  overall_assessment: string;
  priority_dimensions: string[];
  deferred_gap_ids?: string[];
  weekly_plan: WeekPlan[];
  verification: string;
}

export interface AssessmentResult {
  assessment_id?: string;
  user_id: string;
  kind?: string;
  record_origin?: "user" | "agent_test";
  service_id: string;
  service_name: string;
  model_id?: string | null;
  blueprint?: { question_count: number; difficulty_profile: string; focus: string; scope: string; capability_ids: string[] } | null;
  overall_level: string;
  overall_avg?: number;
  rating_reliable?: boolean;
  rating_reason?: string;
  scoring_version?: string;
  choice_score: string;
  answers?: AnswerItem[];
  capability_radar: CapabilityScore[];
  capability_excluded: string[];
  questions: Question[];
  question_results: QuestionResult[];
  learning_plan: LearningPlan | null;
  plan_review?: {
    status: "passed" | "needs_review" | "unverified";
    revision_attempted: boolean;
    revision_applied: boolean;
    remaining_issues: string[];
    critique?: { summary?: string; overall_score?: number };
  } | null;
  prev_capability_radar?: CapabilityScore[] | null;
  comparison?: { comparable: boolean; reason: string; delta: number | null; pre_count: number; post_count: number } | null;
  diagnosis?: KnowledgeGap[];
  agent_trace?: AgentStep[];
  rag_sources?: RetrievedSource[];
}

export interface RetrievedSource {
  document_id: string;
  title: string;
  source_type: "official_doc" | "case" | "learning_path" | string;
  url?: string;
  excerpt?: string;
  score: number;
  capability_id?: string;
  retrieval_method?: string;
}

export interface KnowledgeGap {
  gap_id: string;
  capability_id: string;
  capability_name?: string;
  question_id?: string;
  severity: "critical" | "major" | "minor" | string;
  title: string;
  misunderstanding: string;
  correct_understanding: string;
  evidence_quote?: string;
  suggested_doc_urls?: string[];
}

export interface AgentStep {
  agent: string;
  label?: string;
  input_summary?: string;
  output_summary?: string;
  elapsed_ms?: number;
  timestamp?: string;
  status?: "ok" | "failed" | "skipped" | string;
  error?: string;
}

export interface GenerateResponse {
  session_id: string;
  questions: Question[];
}

export interface UserServiceScore {
  service_id: string;
  service_name: string;
  icon?: string;
  score: number; // 0~5（未测试时为 0）
  is_tested: boolean;
  rating_reliable: boolean;
  is_real: boolean;
  capabilities: CapabilityScore[];
  last_assessed_at: string;
}

export interface UserTrackRadar {
  track_id: string;
  track_name: string;
  icon?: string;
  services: UserServiceScore[];
}

export interface PendingPostTest {
  pending_pre_id: string;
  service_id: string;
  overall_level: string;
  created_at: string;
}

export interface ActivePlan {
  service_id: string;
  service_name: string;
  icon?: string;
  track_id: string;
  track_name: string;
  assessment_id: string;
  overall_level: string;
  overall_avg: number;
  rating_reliable: boolean;
  plan_review?: { status?: string; issues?: string[] };
  created_at: string;
  learning_plan: LearningPlan;
  capability_radar: CapabilityScore[];
  diagnosis?: KnowledgeGap[];
}

// ---------- API ----------

export async function fetchTaxonomy(): Promise<FullTaxonomy> {
  const r = await fetch(`${API_BASE}/api/assessment/taxonomy`, { cache: "no-store" });
  if (!r.ok) throw new Error(`taxonomy ${r.status}`);
  return r.json();
}

export class PendingPostTestError extends Error {
  pending: PendingPostTest;
  constructor(pending: PendingPostTest) {
    super("PENDING_POST_TEST");
    this.pending = pending;
  }
}

// ---------- 异步任务轮询 ----------

/**
 * 轮询一个后台任务直到完成。
 * 后端慢操作（出题/评分/多 agent）返回 {task_id}，这里轮询 /task/{id}。
 */
export type PendingTaskKind = "generate" | "submit" | "post-generate" | "post-submit" | "retry-learning";

function pendingTaskKey(): string {
  const user = getStoredUser();
  return `sage_pending_task_${user?.user_id || "anonymous"}_${user?.current_profile || "unknown"}`;
}

export interface ProfileInsights {
  profile_id: string;
  profile_name: string;
  services: {
    service_id: string; service_name: string; icon: string;
    tested_capability_count: number;
    latest_assessment: { id: string; score: number | null; rating_reliable: boolean; question_count: number; created_at: string } | null;
    capabilities: { id: string; name: string; score: number | null; sample_count: number;
      assessment_id: string | null; assessed_at: string; scoring_version: string | null }[];
  }[];
  plans: { assessment_id: string; service_name: string; plan_name: string;
    total_tasks: number; completed_tasks: number; review_status: string; created_at: string }[];
  ticket_dimensions: { id: string; label: string; score: number | null; sample_count: number;
    latest_ticket_id: string | null; next_step: string }[];
  ticket_count: number;
  trends: { pre_assessment_id: string; post_assessment_id: string; service_id: string;
    pre_score: number; post_score: number; delta: number | null; comparable: boolean;
    reason: string; pre_count: number; post_count: number; created_at: string }[];
  recent_assessments: { assessment_id: string; service_id: string; kind: string; record_origin?: string; created_at: string }[];
}

export async function fetchProfileInsights(userId: string): Promise<ProfileInsights> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/users/${encodeURIComponent(userId)}/profile-insights`, { cache: "no-store" });
  if (!r.ok) throw await apiError(r, "档案加载失败");
  return r.json();
}

export async function fetchLlmStatus(): Promise<{ configured: boolean }> {
  const r = await authenticatedFetch(`${API_BASE}/api/llm/status`, { cache: "no-store" });
  if (!r.ok) throw new Error(`模型状态检查失败 (${r.status})`);
  return r.json();
}

export interface LlmModels {
  configured: boolean;
  default_model: string;
  models: string[];
  discovery_available: boolean;
  warning: string | null;
}

export async function fetchLlmModels(): Promise<LlmModels> {
  const r = await authenticatedFetch(`${API_BASE}/api/llm/models`, { cache: "no-store" });
  if (!r.ok) throw new Error(`模型列表读取失败 (${r.status})`);
  return r.json();
}

export function getPendingTask(): { taskId: string; kind: PendingTaskKind } | null {
  try { return JSON.parse(localStorage.getItem(pendingTaskKey()) || "null"); }
  catch { return null; }
}

async function pollTask<T>(taskId: string, kind: PendingTaskKind, opts?: { intervalMs?: number; timeoutMs?: number }): Promise<T> {
  localStorage.setItem(pendingTaskKey(), JSON.stringify({ taskId, kind }));
  const interval = opts?.intervalMs ?? 2000;
  const timeout = opts?.timeoutMs ?? 300000; // 5 分钟
  const start = Date.now();
  while (true) {
    if (Date.now() - start > timeout) {
      throw new Error("任务超时，请重试");
    }
    await new Promise((res) => setTimeout(res, interval));
    const r = await authenticatedFetch(`${API_BASE}/api/assessment/task/${taskId}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`task poll ${r.status}`);
    const data = await r.json();
    if (data.status === "done") {
      localStorage.removeItem(pendingTaskKey());
      return data.result as T;
    }
    if (data.status === "error") {
      localStorage.removeItem(pendingTaskKey());
      throw new Error(data.error || "任务执行失败");
    }
    // pending / running → 继续轮询
  }
}

export async function generateQuestions(opts: {
  serviceId: string;
  capabilityIds?: string[];
  questionCount?: 6 | 9 | 12 | 18;
  difficultyProfile?: "foundation" | "balanced" | "advanced";
  focus?: "comprehensive" | "configuration" | "troubleshooting" | "architecture";
  modelId?: string;
  studyDays?: number;
  minutesPerDay?: number;
}): Promise<GenerateResponse> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      service_id: opts.serviceId,
      capability_ids: opts.capabilityIds || [],
      question_count: opts.questionCount ?? 9,
      difficulty_profile: opts.difficultyProfile || "balanced",
      focus: opts.focus || "comprehensive",
      model_id: opts.modelId || null,
      study_days: opts.studyDays ?? 5,
      minutes_per_day: opts.minutesPerDay ?? 90,
    }),
  });
  if (r.status === 409) {
    const data = await r.json();
    if (data?.detail?.code === "PENDING_POST_TEST") {
      throw new PendingPostTestError(data.detail.pending);
    }
    throw new Error(`generate 409: ${JSON.stringify(data)}`);
  }
  if (!r.ok) {
    const data = await r.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail : `出题失败 (${r.status})`);
  }
  const { task_id } = await r.json();
  return pollTask<GenerateResponse>(task_id, "generate");
}

export async function submitAssessment(
  answers: AnswerItem[],
  sessionId: string,
): Promise<AssessmentResult> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers, session_id: sessionId }),
  });
  if (!r.ok) throw await apiError(r, "提交测评失败");
  const { task_id } = await r.json();
  return pollTask<AssessmentResult>(task_id, "submit");
}

export async function generatePostTest(prevAssessmentId: string, modelId?: string): Promise<GenerateResponse> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/post-test/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prev_assessment_id: prevAssessmentId, model_id: modelId || null }),
  });
  if (!r.ok) throw await apiError(r, "后测出题失败");
  const { task_id } = await r.json();
  return pollTask<GenerateResponse>(task_id, "post-generate");
}

export async function submitPostTest(
  answers: AnswerItem[],
  sessionId: string,
  prevAssessmentId: string,
): Promise<AssessmentResult> {
  const combined = `${sessionId}:${prevAssessmentId}`;
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/post-test/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers, session_id: combined }),
  });
  if (!r.ok) throw await apiError(r, "后测提交失败");
  const { task_id } = await r.json();
  return pollTask<AssessmentResult>(task_id, "post-submit");
}

export async function fetchUserTrackRadar(userId: string, trackId: string = "big_data"): Promise<UserTrackRadar> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/users/${userId}/track-radar?track_id=${trackId}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`track-radar ${r.status}`);
  return r.json();
}

export async function fetchPendingPostTest(userId: string, serviceId: string): Promise<PendingPostTest | null> {
  const r = await authenticatedFetch(
    `${API_BASE}/api/assessment/users/${userId}/pending-post-test?service_id=${encodeURIComponent(serviceId)}`,
    { cache: "no-store" },
  );
  if (!r.ok) throw new Error(`pending-post-test ${r.status}`);
  const data = await r.json();
  return data.pending || null;
}

export async function fetchActivePlans(userId: string, trackId?: string): Promise<ActivePlan[]> {
  const params = trackId ? `?track_id=${encodeURIComponent(trackId)}` : "";
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/users/${userId}/active-plans${params}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`active-plans ${r.status}`);
  const data = await r.json();
  return data.plans || [];
}

export async function fetchHistory(userId: string): Promise<{
  assessment_id: string;
  kind: string;
  service_id: string;
  overall_level: string;
  overall_avg: number;
  rating_reliable: boolean;
  choice_score: string;
  created_at: string;
}[]> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/history/${userId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`history ${r.status}`);
  const data = await r.json();
  return data.history || [];
}

export interface ArchiveItem {
  assessment_id: string;
  service_id: string;
  kind: string;
  record_origin?: string;
  created_at: string;
  overall_level: string;
  overall_avg: number;
  rating_reliable: boolean;
  plan_name?: string;
  status?: "active" | "completed";
  review_status?: string;
}

export interface ArchivePage<T> { items: T[]; total: number; limit: number; offset: number }

export async function fetchArchive(userId: string, category: "assessments" | "plans", offset = 0, limit = 12,
  filters: { service_id?: string; state?: string; q?: string } = {}): Promise<ArchivePage<ArchiveItem>> {
  const params = new URLSearchParams({ category, offset: String(offset), limit: String(limit), ...filters });
  const response = await authenticatedFetch(`${API_BASE}/api/assessment/archive/${userId}?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`archive ${response.status}`);
  return response.json();
}

// ---------- 团队雷达（管理员看板）----------

export interface TeamMemberRadar {
  user_id: string;
  username: string;
  display_name: string;
  has_tested: boolean;
  radar: UserTrackRadar;
}

export async function fetchTeamRadar(trackId: string = "big_data"): Promise<TeamMemberRadar[]> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/team-radar?track_id=${encodeURIComponent(trackId)}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`team-radar ${r.status}`);
  const data = await r.json();
  return data.members || [];
}

export function resumeTask<T>(taskId: string, kind: PendingTaskKind): Promise<T> {
  return pollTask<T>(taskId, kind);
}

export async function fetchAssessmentResult(assessmentId: string): Promise<AssessmentResult> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/results/${encodeURIComponent(assessmentId)}`);
  if (r.status === 404) throw new Error("记录不存在或不属于当前 Profile；请切回对应方向后重试");
  if (!r.ok) throw new Error(`读取测评报告失败 (${r.status})`);
  return r.json();
}

export async function retryLearning(assessmentId: string): Promise<AssessmentResult> {
  const r = await authenticatedFetch(
    `${API_BASE}/api/assessment/results/${encodeURIComponent(assessmentId)}/retry-learning`,
    { method: "POST" },
  );
  if (!r.ok) throw await apiError(r, "恢复学习计划失败");
  const { task_id } = await r.json();
  return pollTask<AssessmentResult>(task_id, "retry-learning");
}

export async function fetchQuestionSession(sessionId: string): Promise<GenerateResponse & { service_id: string; kind: string; prev_assessment_id: string | null }> {
  const r = await authenticatedFetch(`${API_BASE}/api/assessment/sessions/${encodeURIComponent(sessionId)}`);
  if (!r.ok) throw new Error(`恢复测评失败 (${r.status})`);
  return r.json();
}

// ---------- 故障排查实战 ----------

export interface PracticeScenario {
  id: string;
  service_id: string;
  title: string;
  level: string;
  brief: string;
  objective: string;
  tools?: { id: string; label: string; evidence?: string }[];
}

export interface PracticeRun {
  run_id: string;
  scenario: PracticeScenario;
  inspected_tools: string[];
  status: "in_progress" | "submitted";
  answer: string;
  feedback: null | {
    score: number;
    max_score: number;
    checks: { name: string; passed: boolean }[];
    reference: { root_cause: string; remediation: string; verification: string };
    note: string;
  };
}

export interface PracticeRunSummary {
  run_id: string;
  scenario_id: string;
  title: string;
  status: "in_progress" | "submitted";
  score: number | null;
  created_at: string;
}

async function practiceJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await authenticatedFetch(`${API_BASE}/api/practice${path}`, init);
  if (!r.ok) {
    const error = await r.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : `练习请求失败 (${r.status})`);
  }
  return r.json();
}

export async function fetchPracticeScenarios(): Promise<PracticeScenario[]> {
  const data = await practiceJson<{ scenarios: PracticeScenario[] }>("/scenarios");
  return data.scenarios;
}

export function startPracticeRun(scenarioId: string): Promise<PracticeRun> {
  return practiceJson("/runs", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_id: scenarioId }) });
}

export function fetchPracticeRun(runId: string): Promise<PracticeRun> {
  return practiceJson(`/runs/${encodeURIComponent(runId)}`);
}

export async function fetchPracticeRuns(): Promise<PracticeRunSummary[]> {
  const data = await practiceJson<{ runs: PracticeRunSummary[] }>("/runs");
  return data.runs;
}

export function inspectPracticeTool(runId: string, toolId: string): Promise<{ tool_id: string; evidence: string }> {
  return practiceJson(`/runs/${encodeURIComponent(runId)}/inspect`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool_id: toolId }) });
}

export function submitPracticeRun(runId: string, answer: string): Promise<PracticeRun> {
  return practiceJson(`/runs/${encodeURIComponent(runId)}/submit`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answer }) });
}

// ---------- 模拟客户工单 ----------

export interface TicketOptions {
  profile_id: string;
  services: { id: string; label: string; summary: string }[];
  categories: { id: string; label: string; description: string; curated_case_count: number }[];
  personas: { id: string; label: string; description: string; expertise: number; patience: number; cooperation: number }[];
  impacts: { id: string; label: string }[];
  difficulties: { id: string; label: string }[];
  requires_model: boolean;
}

export interface TicketReport {
  status: "ai_provisional";
  summary: string;
  problem: string;
  user_answer: string;
  reference: { background?: string; scenario?: string; problem: string; investigation_steps?: string[];
    reasoning?: string; root_cause: string; resolution: string; verification: string };
  investigation_steps: string[];
  strengths: string[];
  improvements: string[];
  dimensions: { id: string; label: string; score: number; max_score: number; reason: string;
    weight?: number; not_observed?: boolean;
    citations?: { turn: number; role: string; quote: string }[]; next_step?: string }[];
  overall_score: number;
  scoring_version?: string;
  critical_gap?: boolean;
  sources: string[];
  note: string;
  pending_actions?: { turn: number; text: string; status: string }[];
  case_quality?: { status?: string; source_status?: string; attempts?: unknown[] };
  source_records?: { id: string; url: string; text: string; origin: string }[];
  claim_basis?: { field: string; evidence_ids: string[]; source_ids: string[] }[];
}

export interface TicketSession {
  ticket_id: string;
  service_id: string;
  category: string;
  category_label: string;
  persona_id: string;
  persona_label: string;
  persona_traits: { expertise: number; patience: number; cooperation: number };
  customer_name: string;
  title: string;
  model_id: string;
  impact: string;
  impact_label: string;
  difficulty: string;
  difficulty_label: string;
  cross_service: boolean;
  case_origin: "curated" | "generated";
  case_quality: { status: string; source_status: string; snapshot_sha256?: string };
  customer_state: {
    mood: string;
    collected_evidence: { id: string; label: string }[];
    pending_evidence: { id: string; label: string }[];
    pending_actions: { turn: number; text: string; status: string }[];
    events: { turn: number; summary: string; evidence_ids: string[] }[];
  };
  status: "open" | "closed";
  messages: { role: "customer" | "user"; content: string; evidence_ids?: string[];
    kind?: "final_summary" }[];
  turn_count: number;
  max_turns: number;
  report: TicketReport | null;
  created_at: string;
}

export interface TicketSummary {
  ticket_id: string;
  title: string;
  category_label: string;
  status: "open" | "closed";
  overall_score: number | null;
  created_at: string;
}

export function fetchTicketOptions(): Promise<TicketOptions> {
  return practiceJson("/tickets/options");
}

export async function fetchTickets(): Promise<TicketSummary[]> {
  const data = await practiceJson<{ tickets: TicketSummary[] }>("/tickets?limit=2");
  return data.tickets;
}

export async function fetchTicketArchive(offset = 0, limit = 12,
  filters: { service_id?: string; status?: string; q?: string } = {}): Promise<ArchivePage<TicketSummary>> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), ...filters });
  const data = await practiceJson<{ tickets: TicketSummary[]; total: number; limit: number; offset: number }>(
    `/tickets?${params}`);
  return { items: data.tickets, total: data.total, limit: data.limit, offset: data.offset };
}

export function startTicket(options: { serviceId: string; category: string; personaId: string; modelId?: string;
  impact: string; difficulty: string; crossService: boolean }): Promise<TicketSession> {
  return runTicketJob("/tickets/create-task", { service_id: options.serviceId, category: options.category,
      persona_id: options.personaId, model_id: options.modelId || null, impact: options.impact,
      difficulty: options.difficulty, cross_service: options.crossService });
}

export function fetchTicket(ticketId: string): Promise<TicketSession> {
  return practiceJson(`/tickets/${encodeURIComponent(ticketId)}`);
}

export function sendTicketMessage(ticketId: string, message: string): Promise<TicketSession> {
  return practiceJson(`/tickets/${encodeURIComponent(ticketId)}/messages`, { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) });
}

export function finishTicket(ticketId: string, finalAnswer: string): Promise<TicketSession> {
  return runTicketJob(`/tickets/${encodeURIComponent(ticketId)}/finish-task`, { final_answer: finalAnswer });
}

type TicketJob = { requestId: string; taskId?: string; path: string; body: Record<string, unknown> };
function ticketJobKey() { const user = getStoredUser(); return `sage_ticket_job_${user?.user_id || "anonymous"}_${user?.current_profile || "unknown"}`; }
export function hasPendingTicketJob(): boolean { return !!localStorage.getItem(ticketJobKey()); }

async function runTicketJob(path: string, body: Record<string, unknown>): Promise<TicketSession> {
  if (hasPendingTicketJob()) throw new Error("已有工单任务在处理，请先恢复该任务");
  const job: TicketJob = { requestId: crypto.randomUUID(), path, body };
  localStorage.setItem(ticketJobKey(), JSON.stringify(job));
  return resumeTicketJob();
}

export async function resumeTicketJob(): Promise<TicketSession> {
  const key = ticketJobKey();
  const job = JSON.parse(localStorage.getItem(key) || "null") as TicketJob | null;
  if (!job) throw new Error("没有待恢复的工单任务");
  if (!job.taskId) {
    try {
      const data = await practiceJson<{ task_id: string }>(job.path, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...job.body, request_id: job.requestId }) });
      job.taskId = data.task_id;
      localStorage.setItem(key, JSON.stringify(job));
    } catch (error) {
      // A network error may have occurred after the server accepted the request.
      // Keep the same idempotency key so refresh can safely retry it.
      throw error;
    }
  }
  const started = Date.now();
  while (Date.now() - started < 12 * 60_000) {
    if (ticketJobKey() !== key) throw new Error("登录用户已变化，已停止读取工单任务");
    const task = await practiceJson<{ status: string; result?: TicketSession; error?: string }>(
      `/tickets/tasks/${encodeURIComponent(job.taskId)}`);
    if (task.status === "done" && task.result) {
      localStorage.setItem(`sage_active_ticket_${getStoredUser()?.user_id}_${getStoredUser()?.current_profile}`, task.result.ticket_id);
      localStorage.removeItem(key);
      return task.result;
    }
    if (task.status === "error") {
      localStorage.removeItem(key);
      throw new Error(task.error || "工单任务失败，请重试");
    }
    await new Promise(resolve => setTimeout(resolve, 1800));
  }
  throw new Error("工单任务仍在后台处理，稍后刷新即可恢复");
}

export interface TaskProgress {
  week_index: number;
  task_index: number;
  evidence: string;
  status: string;
  review_note?: string;
  reviewed_by?: string | null;
  updated_at: string;
}

export async function fetchLearningProgress(assessmentId: string): Promise<TaskProgress[]> {
  const r = await authenticatedFetch(`${API_BASE}/api/learning/plans/${encodeURIComponent(assessmentId)}/progress`);
  if (!r.ok) throw new Error(`读取任务进度失败 (${r.status})`);
  return (await r.json()).progress;
}

export async function saveLearningProgress(assessmentId: string, weekIndex: number, taskIndex: number, evidence: string, status: "in_progress" | "blocked" | "submitted" = "submitted"): Promise<TaskProgress> {
  const r = await authenticatedFetch(`${API_BASE}/api/learning/plans/${encodeURIComponent(assessmentId)}/progress`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ week_index: weekIndex, task_index: taskIndex, evidence, status }),
  });
  if (!r.ok) throw new Error(`保存任务进度失败 (${r.status})`);
  return r.json();
}

export interface LearningReviewItem extends TaskProgress {
  id: string; user_id: string; assessment_id: string; service_id: string;
}

export async function fetchLearningReviewQueue(profileId: string): Promise<LearningReviewItem[]> {
  const r = await authenticatedFetch(`${API_BASE}/api/learning/review-queue?profile_id=${encodeURIComponent(profileId)}`);
  if (!r.ok) throw await apiError(r, "读取学习证据失败");
  return (await r.json()).items;
}

export async function reviewLearningProgress(id: string, accepted: boolean, reviewNote: string): Promise<TaskProgress> {
  const r = await authenticatedFetch(`${API_BASE}/api/learning/progress/${encodeURIComponent(id)}/review`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accepted, review_note: reviewNote }),
  });
  if (!r.ok) throw await apiError(r, "验收学习证据失败");
  return r.json();
}

export interface AdminAccount {
  user_id: string;
  username: string;
  display_name: string;
  role: "member" | "manager";
  current_profile: string;
  created_at: string;
  is_active: boolean;
  is_demo: boolean;
  must_change_password: boolean;
}

export interface TeamDashboard {
  profile_id: string;
  days: number;
  metrics: { members: number; enrolled_members: number; assessed_members: number; tested_services: number; total_services: number; active_plans: number };
  members: { user_id: string; username: string; display_name: string; assessment_count: number; ticket_count: number; active_plan_count: number; services: { service_id: string; service_name: string; state: "untested" | "reference" | "observed"; score: number | null; question_count: number; assessment_id: string | null; assessed_at: string | null }[] }[];
  followups: { user_id: string; username: string; reason: string; priority: string }[];
}

export interface TeamMemberDetail {
  member: AdminAccount;
  profile_id: string;
  assessments: { id: string; service_id: string; kind: string; created_at: string; score: number; rating_reliable: boolean; question_count: number; has_plan: boolean }[];
  tickets: { id: string; service_id: string; status: string; created_at: string; category: string }[];
}

export async function fetchTeamMemberDetail(userId: string, profileId: string): Promise<TeamMemberDetail> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/members/${encodeURIComponent(userId)}?profile_id=${encodeURIComponent(profileId)}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取成员明细失败");
  return response.json();
}

export type ManagerRecord =
  { record_type: "assessment"; id: string; service_id: string; kind: string;
    summary: { overall_avg: number; overall_level: string; rating_reliable: boolean; rating_reason: string; question_count: number };
    diagnosis: KnowledgeGap[]; plan_review: { status?: string; remaining_issues?: string[] }; learning_plan: LearningPlan | null; question_results: QuestionResult[] } |
  { record_type: "ticket"; id: string; service_id: string; status: string;
    messages: TicketSession["messages"]; final_answer: string; report: TicketReport | Record<string, never> };

export async function fetchManagerRecord(userId: string, kind: "assessments" | "tickets", recordId: string, profileId: string): Promise<ManagerRecord> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/members/${encodeURIComponent(userId)}/${kind}/${encodeURIComponent(recordId)}?profile_id=${encodeURIComponent(profileId)}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取记录失败");
  return response.json();
}

export async function fetchTeamDashboard(profileId: string, days: 0 | 30 | 90, includeDemo: boolean, enrolledOnly = false): Promise<TeamDashboard> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/dashboard?profile_id=${encodeURIComponent(profileId)}&days=${days}&include_demo=${includeDemo}&enrolled_only=${enrolledOnly}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取团队看板失败");
  return response.json();
}

export async function fetchEnrollments(profileId: string): Promise<string[]> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/enrollments?profile_id=${encodeURIComponent(profileId)}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取培训名单失败");
  return (await response.json()).user_ids;
}

export async function setEnrollment(userId: string, profileId: string, enrolled: boolean): Promise<void> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/enrollments/${encodeURIComponent(userId)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile_id: profileId, enrolled }),
  });
  if (!response.ok) throw await apiError(response, "修改培训名单失败");
}

export async function updateAdminAccountStatus(userId: string, input: { is_active?: boolean; is_demo?: boolean }): Promise<AdminAccount> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/users/${encodeURIComponent(userId)}/status`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "修改账号状态失败");
  return response.json();
}

export async function changeOwnPassword(currentPassword: string, newPassword: string): Promise<void> {
  const response = await authenticatedFetch(`${API_BASE}/api/auth/change-password`, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!response.ok) throw await apiError(response, "修改密码失败");
}

export interface AdminAuditItem { actor_id: string; target_id: string; action: string; detail: string; created_at: string }
export async function fetchAdminAudit(): Promise<AdminAuditItem[]> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/audit`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取操作记录失败");
  return (await response.json()).items;
}

export async function fetchAdminAccounts(): Promise<AdminAccount[]> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/users`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取账号失败");
  return (await response.json()).users;
}

export async function createAdminAccount(input: {
  username: string; display_name: string; password: string; role: "member" | "manager";
}): Promise<AdminAccount> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/users`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "创建账号失败");
  return response.json();
}

export async function resetAdminAccountPassword(userId: string, password: string): Promise<void> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/users/${encodeURIComponent(userId)}/password`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password }),
  });
  if (!response.ok) throw await apiError(response, "重置密码失败");
}

export interface KnowledgeEntry {
  id: string; profile_id: string; service_id: string; capability_id: string;
  source_type: "case" | "official_doc"; title: string; url: string;
  content: string; details: Record<string, string>; source_ticket_id: string | null;
  replaces_entry_id: string | null;
  status: "draft" | "submitted" | "published" | "archived";
  index_status: string; chunk_count: number; created_by: string;
  reviewed_by: string | null; created_at: string; updated_at: string;
}

export interface KnowledgeInput {
  profile_id: string; service_id: string; capability_id: string;
  source_type: "case" | "official_doc"; title: string; url: string;
  details: Record<string, string>; source_ticket_id?: string; replaces_entry_id?: string | null;
}

export async function fetchKnowledgeEntries(profileId = ""): Promise<KnowledgeEntry[]> {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
  const response = await authenticatedFetch(`${API_BASE}/api/knowledge${query}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取知识库失败");
  return response.json();
}

export async function saveKnowledgeEntry(input: KnowledgeInput, id?: string): Promise<KnowledgeEntry> {
  const response = await authenticatedFetch(`${API_BASE}/api/knowledge${id ? `/${encodeURIComponent(id)}` : ""}`, {
    method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "保存知识草稿失败");
  return response.json();
}

export async function actOnKnowledgeEntry(id: string, action: "capture" | "publish" | "archive"): Promise<KnowledgeEntry> {
  const response = await authenticatedFetch(`${API_BASE}/api/knowledge/${encodeURIComponent(id)}/${action}`, { method: "POST" });
  if (!response.ok) throw await apiError(response, "知识库操作失败");
  return response.json();
}

export interface QualityFeedback {
  id: string; user_id: string; profile_id: string; record_type: "assessment" | "ticket";
  record_id: string; question_id: string | null; category: string; description: string;
  original_snapshot: Record<string, unknown>; status: string; review_note: string;
  reviewed_by: string | null; created_at: string; updated_at: string;
}

export async function submitQualityFeedback(input: {
  record_type: "assessment" | "ticket"; record_id: string; question_id?: string;
  category: string; description: string;
}): Promise<QualityFeedback> {
  const response = await authenticatedFetch(`${API_BASE}/api/feedback`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "提交反馈失败");
  return response.json();
}

export async function fetchQualityFeedback(profileId = ""): Promise<QualityFeedback[]> {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
  const response = await authenticatedFetch(`${API_BASE}/api/feedback${query}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取反馈失败");
  return (await response.json()).items;
}

export async function reviewQualityFeedback(id: string, status: "accepted" | "rejected" | "needs_info", review_note: string): Promise<QualityFeedback> {
  const response = await authenticatedFetch(`${API_BASE}/api/feedback/${encodeURIComponent(id)}/review`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, review_note }),
  });
  if (!response.ok) throw await apiError(response, "复核失败");
  return response.json();
}

export interface TrainingAssignment {
  id: string; user_id: string; profile_id: string; service_id: string;
  kind: "assessment" | "ticket"; capability_id: string; question_count: number;
  difficulty_profile: "foundation" | "balanced" | "advanced";
  focus: "comprehensive" | "configuration" | "troubleshooting" | "architecture";
  scoring_version: string; note: string;
  due_at: string | null; created_by: string; created_at: string;
  status: "pending" | "overdue" | "completed"; evidence_id: string;
}

export async function fetchAssignments(profileId = ""): Promise<TrainingAssignment[]> {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
  const response = await authenticatedFetch(`${API_BASE}/api/assignments${query}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取培训任务失败");
  return (await response.json()).items;
}

export async function createAssignment(input: {
  user_id: string; profile_id: string; service_id: string; kind: "assessment" | "ticket";
  capability_id: string; question_count: number; difficulty_profile: string;
  focus: TrainingAssignment["focus"];
  note: string; due_at: string | null;
}): Promise<TrainingAssignment> {
  const response = await authenticatedFetch(`${API_BASE}/api/assignments`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, "布置培训失败");
  return response.json();
}

export interface OperationMetrics {
  profile_id: string; days: number; sample_count: number; truncated: boolean;
  by_kind: { kind: string; total: number; done: number; error: number; pending: number;
    p50_ms: number | null; p95_ms: number | null }[];
  by_model: Record<string, { calls: number; failed: number; prompt_tokens: number;
    completion_tokens: number; token_usage_missing: number }>;
  estimated_usd: number | null; unpriced_calls: number; unobserved_tasks: number; note: string;
}

export async function fetchOperationMetrics(profileId: string, days: 7 | 30 | 90): Promise<OperationMetrics> {
  const response = await authenticatedFetch(`${API_BASE}/api/admin/operations?profile_id=${encodeURIComponent(profileId)}&days=${days}`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取运行指标失败");
  return response.json();
}

export async function reindexKnowledge(): Promise<{ index_status: string }> {
  const response = await authenticatedFetch(`${API_BASE}/api/knowledge/reindex`, { method: "POST" });
  if (!response.ok) throw await apiError(response, "重建索引失败");
  return response.json();
}

export interface KnowledgeCoverage {
  service_count: number; services_with_chunks: number; chunk_count: number;
  chunks_by_type: Record<string, number>;
  services: { profile_id: string; service_id: string; chunks: number;
    official_refs: number; official_excerpts: number }[];
}

export async function fetchKnowledgeCoverage(): Promise<KnowledgeCoverage> {
  const response = await authenticatedFetch(`${API_BASE}/api/knowledge/coverage`, { cache: "no-store" });
  if (!response.ok) throw await apiError(response, "读取知识覆盖失败");
  return response.json();
}

/**
 * 后端 API 封装 (v3 - 三层 Track/Service/Capability)。
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

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
    }
  | {
      id: string;
      type: "open";
      dimension_id: string;
      difficulty?: string;
      question: string;
      scoring_rubric?: string[];
      reference_answer?: string;
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
  weekly_plan: WeekPlan[];
  verification: string;
}

export interface AssessmentResult {
  assessment_id?: string;
  user_id: string;
  kind?: string;
  service_id: string;
  service_name: string;
  overall_level: string;
  choice_score: string;
  capability_radar: CapabilityScore[];
  capability_excluded: string[];
  questions: Question[];
  question_results: QuestionResult[];
  learning_plan: LearningPlan | null;
  prev_capability_radar?: CapabilityScore[] | null;
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
async function pollTask<T>(taskId: string, opts?: { intervalMs?: number; timeoutMs?: number }): Promise<T> {
  const interval = opts?.intervalMs ?? 2000;
  const timeout = opts?.timeoutMs ?? 300000; // 5 分钟
  const start = Date.now();
  while (true) {
    if (Date.now() - start > timeout) {
      throw new Error("任务超时，请重试");
    }
    await new Promise((res) => setTimeout(res, interval));
    const r = await fetch(`${API_BASE}/api/assessment/task/${taskId}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`task poll ${r.status}`);
    const data = await r.json();
    if (data.status === "done") return data.result as T;
    if (data.status === "error") throw new Error(data.error || "任务执行失败");
    // pending / running → 继续轮询
  }
}

export async function generateQuestions(opts: {
  serviceId: string;
  capabilityIds?: string[];
  numChoice?: number;
  numOpen?: number;
  difficulty?: string;
}): Promise<GenerateResponse> {
  const r = await fetch(`${API_BASE}/api/assessment/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: "demo_user",
      service_id: opts.serviceId,
      capability_ids: opts.capabilityIds || [],
      num_choice: opts.numChoice ?? 6,
      num_open: opts.numOpen ?? 3,
      difficulty: opts.difficulty || "",
    }),
  });
  if (r.status === 409) {
    const data = await r.json();
    if (data?.detail?.code === "PENDING_POST_TEST") {
      throw new PendingPostTestError(data.detail.pending);
    }
    throw new Error(`generate 409: ${JSON.stringify(data)}`);
  }
  if (!r.ok) throw new Error(`generate ${r.status}: ${await r.text()}`);
  const { task_id } = await r.json();
  return pollTask<GenerateResponse>(task_id);
}

export async function submitAssessment(
  userId: string,
  answers: AnswerItem[],
  sessionId: string,
): Promise<AssessmentResult> {
  const r = await fetch(`${API_BASE}/api/assessment/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, answers, session_id: sessionId }),
  });
  if (!r.ok) throw new Error(`submit ${r.status}: ${await r.text()}`);
  const { task_id } = await r.json();
  return pollTask<AssessmentResult>(task_id);
}

export async function generatePostTest(prevAssessmentId: string): Promise<GenerateResponse> {
  const r = await fetch(`${API_BASE}/api/assessment/post-test/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: "demo_user", prev_assessment_id: prevAssessmentId }),
  });
  if (!r.ok) throw new Error(`post-test generate ${r.status}: ${await r.text()}`);
  const { task_id } = await r.json();
  return pollTask<GenerateResponse>(task_id);
}

export async function submitPostTest(
  userId: string,
  answers: AnswerItem[],
  sessionId: string,
  prevAssessmentId: string,
): Promise<AssessmentResult> {
  const combined = `${sessionId}:${prevAssessmentId}`;
  const r = await fetch(`${API_BASE}/api/assessment/post-test/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, answers, session_id: combined }),
  });
  if (!r.ok) throw new Error(`post-test submit ${r.status}: ${await r.text()}`);
  const { task_id } = await r.json();
  return pollTask<AssessmentResult>(task_id);
}

export async function fetchUserTrackRadar(userId: string, trackId: string = "big_data"): Promise<UserTrackRadar> {
  const r = await fetch(`${API_BASE}/api/assessment/users/${userId}/track-radar?track_id=${trackId}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`track-radar ${r.status}`);
  return r.json();
}

export async function fetchPendingPostTest(userId: string, serviceId: string): Promise<PendingPostTest | null> {
  const r = await fetch(
    `${API_BASE}/api/assessment/users/${userId}/pending-post-test?service_id=${encodeURIComponent(serviceId)}`,
    { cache: "no-store" },
  );
  if (!r.ok) throw new Error(`pending-post-test ${r.status}`);
  const data = await r.json();
  return data.pending || null;
}

export async function fetchActivePlans(userId: string, trackId?: string): Promise<ActivePlan[]> {
  const params = trackId ? `?track_id=${encodeURIComponent(trackId)}` : "";
  const r = await fetch(`${API_BASE}/api/assessment/users/${userId}/active-plans${params}`, {
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
  choice_score: string;
  created_at: string;
}[]> {
  const r = await fetch(`${API_BASE}/api/assessment/history/${userId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`history ${r.status}`);
  const data = await r.json();
  return data.history || [];
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
  const r = await fetch(`${API_BASE}/api/assessment/team-radar?track_id=${encodeURIComponent(trackId)}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`team-radar ${r.status}`);
  const data = await r.json();
  return data.members || [];
}

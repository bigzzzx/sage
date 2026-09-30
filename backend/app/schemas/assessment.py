"""测评相关的数据模型（v2 - 三层结构）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


# ---------- 请求 ----------

class AnswerItem(BaseModel):
    question_id: str
    answer: str


class GenerateRequest(BaseModel):
    """动态出题请求（基于 Service）。"""
    service_id: str  # 必填：考哪个服务
    capability_ids: list[str] = []  # 空=全部 capability
    question_count: Literal[6, 9, 12, 18] = 9
    difficulty_profile: Literal["foundation", "balanced", "advanced"] = "balanced"
    focus: Literal["comprehensive", "configuration", "troubleshooting", "architecture"] = "comprehensive"
    generation_model: str | None = Field(default=None, alias="model_id", max_length=128)
    study_days: int = Field(default=5, ge=1, le=7)
    minutes_per_day: int = Field(default=90, ge=30, le=180)


class SubmitRequest(BaseModel):
    session_id: str = ""
    answers: list[AnswerItem]


class PostTestRequest(BaseModel):
    prev_assessment_id: str
    generation_model: str | None = Field(default=None, alias="model_id", max_length=128)


# ---------- 响应 ----------

class ScoreDetail(BaseModel):
    # L1 维度
    accuracy: float = 0
    completeness: float = 0
    clarity: float = 0
    # L2 维度
    logical_flow: float = 0
    technical_depth: float = 0
    # L3 维度
    systematic_approach: float = 0
    root_cause_identification: float = 0
    solution_feasibility: float = 0
    before_after_clarity: float = 0
    # 兼容旧数据
    diagnostic_approach: float = 0
    depth: float = 0
    practicality: float = 0


class QuestionResult(BaseModel):
    question_id: str
    type: str
    is_correct: bool | None = None
    score_detail: ScoreDetail | None = None
    total_score: float = 0
    level: str = ""
    feedback: str = ""
    scoring_version: str = "legacy"


class CapabilityScore(BaseModel):
    """单个 capability 的得分（属于一个 service）。"""
    service_id: str
    service_name: str
    capability_id: str
    capability_name: str
    score: float  # 0~5
    sample_count: int = 0


class ServiceScore(BaseModel):
    """单个 Service 的综合得分（用于雷达图维度）。"""
    service_id: str
    service_name: str
    score: float  # 0~5
    is_real: bool = True  # 是否是真实测评（vs 历史/默认）
    capabilities: list[CapabilityScore] = []
    sample_count: int = 0


class TrackRadar(BaseModel):
    """一个 Track 的雷达图：以 Service 为维度。"""
    track_id: str
    track_name: str
    services: list[ServiceScore] = []


class LearningTask(BaseModel):
    day: str
    topic: str
    task_type: str = "reading"  # reading / review / lab / quiz
    targets_gap_ids: list[str] = []  # 本 task 直击的盲区 id（agent 化后的关键链路）
    objective: str = ""  # 本任务学习目标（一句话）
    deliverable: str = ""  # 预期产出物（完成后能交付什么）
    # 核心概念，每条 LLM 给 search_query，后端拼成搜索 URL 后写入 url 字段
    concepts: list[dict] = []  # [{"point": "...", "search_query": "...", "url": "<auto>"}]
    hands_on: str = ""  # 实操步骤说明（多行）
    preconditions: str = ""  # 实操所需账号、权限、资源和预置环境
    verification_steps: str = ""  # 可观察的验收步骤；未实测时不得写成已通过
    risk_and_cleanup: str = ""  # 费用/变更风险、回滚和资源清理
    hands_on_search: str = ""  # 实操参考的搜索关键词
    hands_on_url: str = ""  # 后端根据 hands_on_search 自动拼接的搜索 URL
    troubleshooting: str = ""  # 故障排查练习
    description: str = ""  # 兼容旧字段
    resources: list[dict] = []  # 兼容旧字段
    time_minutes: int = 60


class WeekPlan(BaseModel):
    week: int
    focus: str
    tasks: list[LearningTask] = []


class LearningPlan(BaseModel):
    plan_name: str = ""
    overall_assessment: str = ""
    priority_dimensions: list[str] = []
    deferred_gap_ids: list[str] = []
    weekly_plan: list[WeekPlan] = []
    verification: str = ""


class RetrievedSource(BaseModel):
    document_id: str
    title: str
    source_type: str
    url: str = ""
    excerpt: str = ""
    score: float = 0
    capability_id: str = ""
    retrieval_method: str = "keyword"


class KnowledgeGap(BaseModel):
    """单个知识盲区（诊断 agent 输出的最小单位）。"""
    gap_id: str  # 唯一 id，如 "gap_q3_sg_self_ref"
    capability_id: str
    capability_name: str = ""
    question_id: str = ""  # 来源题目
    severity: str = "minor"  # critical / major / minor
    title: str = ""  # 盲区标题，~10 字内，如 "SG 自引用规则"
    misunderstanding: str = ""  # 用户具体的错误理解
    correct_understanding: str = ""  # 正确理解应是什么
    evidence_quote: str = ""  # 从用户回答里截的关键句（证据）
    suggested_doc_urls: list[str] = []  # 诊断 agent 从白名单挑的最对症文档


class AgentStep(BaseModel):
    """Agent trace 中的一步。"""
    agent: str  # diagnosis / planning / reflection / scoring 等
    label: str = ""  # 这一步的标题，给前端展示用
    input_summary: str = ""
    output_summary: str = ""
    elapsed_ms: int = 0
    timestamp: str = ""
    status: str = "ok"  # ok / failed / skipped
    error: str = ""


class AssessmentResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    assessment_id: str = ""
    user_id: str
    kind: str = "pre"
    record_origin: str = "user"
    service_id: str = ""
    model_id: str | None = None
    service_name: str = ""
    blueprint: dict | None = None
    overall_level: str
    overall_avg: float = 0
    rating_reliable: bool = False
    rating_reason: str = ""
    scoring_version: str = "legacy"
    choice_score: str
    answers: list[AnswerItem] = []
    # 本次测评的 capability 级雷达（在该 service 内）
    capability_radar: list[CapabilityScore] = []
    capability_excluded: list[str] = []
    questions: list[dict] = []
    question_results: list[QuestionResult]
    learning_plan: LearningPlan | None = None
    plan_review: dict | None = None
    # 后测对比
    prev_capability_radar: list[CapabilityScore] | None = None
    comparison: dict | None = None
    # Agent 化新增
    diagnosis: list[KnowledgeGap] = []
    agent_trace: list[AgentStep] = []
    rag_sources: list[RetrievedSource] = []


class GenerateResponse(BaseModel):
    session_id: str
    questions: list[dict]


class HistoryItem(BaseModel):
    assessment_id: str
    kind: str
    service_id: str
    overall_level: str
    overall_avg: float
    choice_score: str
    created_at: str
    prev_assessment_id: str | None = None

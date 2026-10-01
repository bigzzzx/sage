"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import {
  fetchPendingPostTest,
  fetchLlmStatus,
  fetchLlmModels,
  fetchHistory,
  fetchAssessmentResult,
  fetchQuestionSession,
  fetchTaxonomy,
  generateQuestions,
  getPendingTask,
  PendingPostTestError,
  resumeTask,
  submitAssessment,
  type AnswerItem,
  type AssessmentResult,
  type FullTaxonomy,
  type GenerateResponse,
  type LlmModels,
  type PendingPostTest,
  type Question,
  type ServiceDef,
} from "@/lib/api";

type Phase = "setup" | "generating" | "answering" | "submitting";

export default function AssessmentPage() {
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getStoredUser>>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      setUser(getStoredUser());
      setHydrated(true);
    });
  }, []);

  const userId = user?.user_id || "";
  const role = user?.role;

  useEffect(() => {
    if (!hydrated) return;
    if (!userId) router.replace("/login");
    else if (role === "manager") router.replace("/");
  }, [hydrated, router, userId, role]);

  const userProfile = user?.current_profile || "big_data";

  const [phase, setPhase] = useState<Phase>("setup");
  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const trackId = userProfile;
  const [serviceId, setServiceId] = useState<string>("");
  const [selectedCaps, setSelectedCaps] = useState<string[]>([]);
  const [questionCount, setQuestionCount] = useState<6 | 12 | 18>(12);
  const [difficultyProfile, setDifficultyProfile] = useState<"foundation" | "balanced" | "advanced">("balanced");
  const [focus, setFocus] = useState<"comprehensive" | "configuration" | "troubleshooting" | "architecture">("comprehensive");
  const [weaknessNote, setWeaknessNote] = useState("");
  const [weaknessLoading, setWeaknessLoading] = useState(false);

  const [sessionId, setSessionId] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const [llmModels, setLlmModels] = useState<LlmModels | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [studyDays, setStudyDays] = useState(5);
  const [minutesPerDay, setMinutesPerDay] = useState(90);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingPostTest | null>(null);
  const draftKey = `sage_assessment_draft_${user?.user_id || "anonymous"}_${userProfile}`;
  const modelPreferenceKey = `sage_generation_model_${user?.user_id || "anonymous"}_${userProfile}`;

  const refreshModels = useCallback(async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const info = await fetchLlmModels();
      setLlmModels(info);
      const saved = localStorage.getItem(modelPreferenceKey);
      const preferred = saved && info.models.includes(saved)
        ? saved
        : info.default_model || info.models[0] || "";
      setSelectedModel(preferred);
      if (preferred) localStorage.setItem(modelPreferenceKey, preferred);
    } catch (reason) {
      setModelsError(String(reason));
    } finally {
      setModelsLoading(false);
    }
  }, [modelPreferenceKey]);

  useEffect(() => {
    if (!userId) return;
    fetchLlmStatus().then(status => setLlmConfigured(status.configured)).catch(() => setLlmConfigured(null));
    let active = true;
    queueMicrotask(() => { if (active) void refreshModels(); });
    return () => { active = false; };
  }, [userId, refreshModels]);

  useEffect(() => {
    if (!user?.user_id) return;
    const savedTask = getPendingTask();
    if (savedTask?.kind === "generate") {
      queueMicrotask(() => setPhase("generating"));
      resumeTask<GenerateResponse>(savedTask.taskId, savedTask.kind)
        .then(async (response) => {
          const session = await fetchQuestionSession(response.session_id);
          setServiceId(session.service_id);
          setSessionId(response.session_id);
          setQuestions(response.questions);
          setPhase("answering");
        })
        .catch((reason) => { setError(String(reason)); setPhase("setup"); });
      return;
    }
    if (savedTask?.kind === "submit") {
      queueMicrotask(() => setPhase("submitting"));
      resumeTask<AssessmentResult>(savedTask.taskId, savedTask.kind)
        .then((result) => { localStorage.removeItem(draftKey); router.push(`/result?id=${result.assessment_id}`); })
        .catch((reason) => { setError(String(reason)); setPhase("answering"); });
      return;
    }
    const legacyDraftKey = `sage_assessment_draft_${user?.user_id || "anonymous"}`;
    const draft = localStorage.getItem(draftKey) || localStorage.getItem(legacyDraftKey);
    if (!draft) return;
    try {
      const saved = JSON.parse(draft);
      fetchQuestionSession(saved.sessionId).then((session) => {
        if (session.kind !== "pre") return;
        if (localStorage.getItem(legacyDraftKey) === draft) {
          localStorage.setItem(draftKey, draft);
          localStorage.removeItem(legacyDraftKey);
        }
        setServiceId(session.service_id);
        setSessionId(saved.sessionId);
        setQuestions(session.questions);
        setAnswers(saved.answers || {});
        setPhase("answering");
      }).catch(() => { if (localStorage.getItem(draftKey) === draft) localStorage.removeItem(draftKey); });
    } catch { if (localStorage.getItem(draftKey) === draft) localStorage.removeItem(draftKey); }
  }, [user?.user_id, draftKey, router]);

  useEffect(() => {
    if (phase === "answering" && sessionId) {
      localStorage.setItem(draftKey, JSON.stringify({ sessionId, answers }));
    }
  }, [phase, sessionId, answers, draftKey]);

  useEffect(() => {
    fetchTaxonomy().then(setTaxonomy).catch((e) => setError(String(e)));
  }, []);

  // 选择服务后检查是否有未完成的后测
  useEffect(() => {
    if (!serviceId) {
      queueMicrotask(() => setPending(null));
      return;
    }
    fetchPendingPostTest(user?.user_id || "", serviceId)
      .then(setPending)
      .catch(() => setPending(null));
  }, [serviceId, user?.user_id]);

  const currentTrack = useMemo(
    () => taxonomy?.tracks.find((t) => t.id === trackId),
    [taxonomy, trackId],
  );
  const currentService: ServiceDef | undefined = useMemo(
    () => currentTrack?.services.find((s) => s.id === serviceId),
    [currentTrack, serviceId],
  );

  useEffect(() => {
    if (!currentTrack || phase !== "setup") return;
    const params = new URLSearchParams(window.location.search);
    const requestedService = params.get("service");
    const requestedCapability = params.get("capability");
    const requestedCount = Number(params.get("count"));
    const requestedDifficulty = params.get("difficulty");
    const requestedFocus = params.get("focus");
    const assigned = Boolean(params.get("assignment"));
    if (!requestedService) return;
    const service = currentTrack.services.find(item => item.id === requestedService);
    if (!service) {
      queueMicrotask(() => setWeaknessNote("原报告中的服务不属于当前 Profile，请手动选择练习范围。"));
      return;
    }
    queueMicrotask(() => {
      setServiceId(service.id);
      if ([6, 12, 18].includes(requestedCount)) setQuestionCount(requestedCount as 6 | 12 | 18);
      if (["foundation", "balanced", "advanced"].includes(requestedDifficulty || ""))
        setDifficultyProfile(requestedDifficulty as "foundation" | "balanced" | "advanced");
      if (["comprehensive", "configuration", "troubleshooting", "architecture"].includes(requestedFocus || ""))
        setFocus(requestedFocus as typeof focus);
      if (requestedCapability && service.capabilities?.some(item => item.id === requestedCapability)) {
        setSelectedCaps([requestedCapability]);
        setWeaknessNote(assigned
          ? "已带入培训任务的能力点和出题配置。修改题量、难度、侧重点或能力点后，本次记录可能不计入该任务完成状态。"
          : "已根据报告选中薄弱能力点；可调整题量和难度后开始针对性测评。此为新测评，不会覆盖原报告。");
      } else {
        setWeaknessNote(assigned
          ? "已带入培训任务的综合测评配置。修改题量、难度、侧重点或能力点后，本次记录可能不计入该任务完成状态。"
          : "已根据报告选中服务；请确认能力点后开始新测评。此为新测评，不会覆盖原报告。");
      }
    });
  }, [currentTrack, phase]);

  const toggleCap = (capId: string) => {
    setSelectedCaps((prev) =>
      prev.includes(capId) ? prev.filter((x) => x !== capId) : prev.length < 3 ? [...prev, capId] : prev,
    );
  };

  async function selectRecentWeaknesses() {
    if (!userId || !serviceId) return;
    setWeaknessLoading(true);
    setWeaknessNote("");
    try {
      const history = await fetchHistory(userId);
      const latest = history.find(item => item.service_id === serviceId && item.kind === "pre");
      if (!latest) {
        setWeaknessNote("该服务暂无前测记录，请先使用综合或手选能力点。");
        return;
      }
      const report = await fetchAssessmentResult(latest.assessment_id);
      const allowed = new Set(currentService?.capabilities?.map(cap => cap.id) || []);
      const weak = (report.capability_radar || [])
        .filter(cap => allowed.has(cap.capability_id) && cap.sample_count >= 2 && cap.score < 3.5)
        .sort((a, b) => a.score - b.score)
        .slice(0, 3).map(cap => cap.capability_id);
      if (!weak.length) {
        setWeaknessNote("最近前测没有足够证据支持的薄弱能力点（每点至少 2 题且低于 3.5 分）；可手动选择。");
        return;
      }
      setSelectedCaps(weak);
      setWeaknessNote(`已选择 ${weak.length} 个历史薄弱能力点。请检查下方高亮项，再开始测评。`);
    } catch (reason) {
      setWeaknessNote(`读取历史测评失败：${String(reason)}`);
    } finally {
      setWeaknessLoading(false);
    }
  }

  async function startGenerate() {
    if (!serviceId) {
      setError("请先选择一个服务");
      return;
    }
    setPhase("generating");
    setError(null);
    try {
      const resp = await generateQuestions({
        serviceId,
        capabilityIds: selectedCaps.length > 0 ? selectedCaps : undefined,
        questionCount,
        difficultyProfile,
        focus,
        modelId: selectedModel,
        studyDays,
        minutesPerDay,
      });
      setSessionId(resp.session_id);
      setQuestions(resp.questions);
      setAnswers({});
      setPhase("answering");
    } catch (e) {
      if (e instanceof PendingPostTestError) {
        setPending(e.pending);
        setError(null);
      } else {
        setError(String(e));
      }
      setPhase("setup");
    }
  }

  const choiceQs = questions.filter((q) => q.type === "choice");
  const openQs = questions.filter((q) => q.type === "open");

  const updateAnswer = (qid: string, val: string) =>
    setAnswers((prev) => ({ ...prev, [qid]: val }));

  const answeredCount = Object.values(answers).filter((v) => v.trim()).length;
  const allAnswered = answeredCount === questions.length && questions.length > 0;

  async function onSubmit() {
    setPhase("submitting");
    setError(null);
    try {
      const items: AnswerItem[] = questions.map((q) => ({
        question_id: q.id,
        answer: answers[q.id] || "",
      }));
      const result = await submitAssessment(items, sessionId);
      localStorage.removeItem(draftKey);
      router.push(`/result?id=${result.assessment_id}`);
    } catch (e) {
      setError(String(e));
      setPhase("answering");
    }
  }

  // ---------- Setup ----------
  if (phase === "setup") {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 py-10 px-4">
        <div className="sage-content mx-auto max-w-4xl">
          <header className="mb-8">
            <p className="text-xs font-semibold tracking-[0.2em] text-emerald-400">
              SKILL ASSESSMENT
            </p>
            <h1 className="sage-page-title mt-2 text-3xl font-bold">能力测评</h1>
            <p className="sage-page-description mt-2 text-sm text-slate-400">
              选择职业方向 → 服务 → 能力点，AI 实时为你出题
            </p>
          </header>

          {error && <p className="text-rose-400 mb-4">{error}</p>}
          {llmConfigured === false && <div className="mb-6 rounded-xl border border-amber-700 bg-amber-950/40 p-4 text-sm text-amber-200">
            当前服务端尚未配置模型密钥，AI 测评与模拟工单暂不可用。你仍可先体验 <a href="/practice/legacy" className="font-semibold underline">经典固定场景练习</a>。
          </div>}
          {llmConfigured === null && <div className="mb-6 rounded-xl border border-slate-700 bg-slate-800 p-4 text-sm text-slate-300">正在确认模型配置；若持续未完成，请检查后端连接并刷新页面。</div>}

          <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800/70 p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">本次出题模型</h2>
                <p className="mt-1 text-xs text-slate-400">从已配置的模型服务读取可用模型；新增模型后点刷新即可发现。</p>
              </div>
              <button type="button" onClick={() => void refreshModels()} disabled={modelsLoading}
                className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:border-emerald-500 disabled:opacity-50">
                {modelsLoading ? "正在读取…" : "↻ 刷新模型列表"}
              </button>
            </div>
            <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center">
              <label htmlFor="assessment-model" className="text-sm text-slate-300 sm:w-28">选择模型</label>
              <select id="assessment-model" value={selectedModel}
                onChange={(event) => {
                  setSelectedModel(event.target.value);
                  localStorage.setItem(modelPreferenceKey, event.target.value);
                }}
                disabled={modelsLoading || !llmModels?.models.length}
                className="w-full rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-sm text-slate-100 disabled:opacity-50 sm:flex-1">
                {!llmModels?.models.length && <option value="">暂无可用模型</option>}
                {llmModels?.models.map((model) => <option key={model} value={model}>{model}{model === llmModels.default_model ? "（默认）" : ""}</option>)}
              </select>
            </div>
            {modelsError && <p className="mt-2 text-sm text-rose-300">{modelsError}</p>}
            {llmModels?.warning && <p className="mt-2 text-xs text-amber-300">{llmModels.warning}。可检查服务商是否支持 OpenAI 兼容的模型列表接口。</p>}
            {llmModels?.discovery_available && <p className="mt-2 text-xs text-emerald-300">已发现 {llmModels.models.length} 个模型；所选模型用于本次出题、评分、诊断及计划。后测使用届时保存的模型选择。</p>}
          </section>

          <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800/70 p-5">
            <h2 className="font-semibold">学习时间安排</h2>
            <p className="mt-1 text-xs text-slate-400">提交测评后，学习计划会按这里的时间预算生成。</p>
            <div className="mt-4 flex flex-wrap gap-4">
              <label className="text-sm text-slate-300">
                学习天数
                <select value={studyDays} onChange={(event) => setStudyDays(Number(event.target.value))}
                  className="ml-2 rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100">
                  {[1, 2, 3, 4, 5, 6, 7].map((days) => <option key={days} value={days}>{days} 天</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-300">
                每天可投入
                <select value={minutesPerDay} onChange={(event) => setMinutesPerDay(Number(event.target.value))}
                  className="ml-2 rounded-lg border border-slate-600 bg-slate-900 px-3 py-2 text-slate-100">
                  {[30, 60, 90, 120, 180].map((minutes) => <option key={minutes} value={minutes}>{minutes} 分钟</option>)}
                </select>
              </label>
            </div>
          </section>

          {!taxonomy ? (
            <p className="text-slate-400">加载中…</p>
          ) : !currentTrack ? (
            <div className="text-center py-16">
              <p className="text-2xl mb-4">🚧</p>
              <p className="text-slate-300 text-lg font-medium mb-2">
                该方向暂无测评内容
              </p>
              <p className="text-slate-500 text-sm">
                当前 Profile 暂未配置能力体系，敬请期待
              </p>
            </div>
          ) : (
            <>
              {/* Step 1: Service */}
              {currentTrack && (
                <section className="mb-8">
                  <div className="text-xs text-emerald-400 mb-2">STEP 1</div>
                  <h2 className="text-lg font-semibold mb-3">选择服务</h2>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    {currentTrack.services.map((s) => {
                      const active = s.id === serviceId;
                      return (
                        <button
                          key={s.id}
                          onClick={() => {
                            setServiceId(s.id);
                            setSelectedCaps([]);
                            setWeaknessNote("");
                          }}
                          className={`text-left p-4 rounded-lg border transition-all relative ${
                            active
                              ? "bg-emerald-500/15 border-emerald-500"
                              : "bg-slate-800/60 border-slate-700 hover:border-slate-500"
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xl">{s.icon}</span>
                            <span className="font-medium text-sm">
                              {active && "✓ "}
                              {s.name}
                            </span>
                          </div>
                          <div className="text-xs text-slate-400">
                            {s.summary}
                          </div>
                          {!s.is_real && (
                            <></>
                          )}
                        </button>
                      );
                    })}
                  </div>
                  {currentService && !currentService.is_real && (
                    <></>
                  )}
                </section>
              )}

              {/* 待办后测提示 */}
              {pending && (
                <section className="mb-8">
                  <div className="bg-amber-500/10 border border-amber-500/40 rounded-lg p-5">
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">📝</span>
                      <div className="flex-1">
                        <h3 className="font-semibold text-amber-300 mb-1">
                          上一轮测评尚未完成验证
                        </h3>
                        <p className="text-sm text-slate-300 leading-relaxed mb-3">
                          你在 <b>{currentService?.name}</b> 上有一份{" "}
                          <span className="font-mono text-amber-400">
                            {pending.overall_level}
                          </span>{" "}
                          级别的前测（{new Date(pending.created_at).toLocaleString()}），
                          请先完成对应的<b>后测验证</b>，把学习成果落实之后再开始新一轮测评。
                        </p>
                        <a
                          href={`/post-test?prev=${pending.pending_pre_id}`}
                          className="inline-block px-4 py-2 bg-amber-600 hover:bg-amber-500 rounded text-white text-sm font-medium transition-colors"
                        >
                          📝 立即去做后测验证 →
                        </a>
                      </div>
                    </div>
                  </div>
                </section>
              )}

              {/* Step 2: Capability */}
              {currentService && !pending && (
                <section className="mb-8">
                  <div className="text-xs text-emerald-400 mb-2">STEP 2</div>
                  <h2 className="text-lg font-semibold mb-3">
                    选择能力点{" "}
                    <span className="text-sm text-slate-400 font-normal">
                      (不选 = 综合测评；最多选 3 个 = 专项测评)
                    </span>
                  </h2>
                  <button type="button" onClick={() => void selectRecentWeaknesses()} disabled={weaknessLoading}
                    className="mb-3 rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200 hover:border-emerald-500 disabled:opacity-50">
                    {weaknessLoading ? "正在读取历史…" : "按最近测评薄弱项选择"}
                  </button>
                  {weaknessNote && <p className="mb-3 text-xs text-amber-300">{weaknessNote}</p>}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {(currentService.capabilities || []).map((c) => {
                      const active = selectedCaps.includes(c.id);
                      return (
                        <button
                          key={c.id}
                          onClick={() => toggleCap(c.id)}
                          className={`text-left p-3 rounded-lg border transition-all ${
                            active
                              ? "bg-emerald-500/15 border-emerald-500"
                              : "bg-slate-800/60 border-slate-700 hover:border-slate-500"
                          }`}
                        >
                          <div className="font-medium text-sm">
                            {active && "✓ "}
                            {c.name}
                          </div>
                          <div className="text-xs text-slate-400 mt-1">
                            {c.description}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </section>
              )}

              {/* 测评蓝图 */}
              {currentService && !pending && (
                <section className="mb-8 rounded-xl border border-slate-700 bg-slate-800/70 p-5">
                  <h2 className="font-semibold mb-1">本次测评蓝图</h2>
                  <p className="text-xs text-slate-400 mb-4">题量、难度与侧重点会传到服务端并校验；短测仅作快速诊断，不能代表全部能力。</p>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <label className="text-sm">题量
                      <select value={questionCount} onChange={e => setQuestionCount(Number(e.target.value) as 6 | 12 | 18)} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-2">
                        <option value={6}>快速 · 6 题</option><option value={12}>标准 · 12 题</option><option value={18}>深入 · 18 题</option>
                      </select>
                    </label>
                    <label className="text-sm">难度方向
                      <select value={difficultyProfile} onChange={e => setDifficultyProfile(e.target.value as typeof difficultyProfile)} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-2">
                        <option value="foundation">基础优先</option><option value="balanced">均衡</option><option value="advanced">进阶优先</option>
                      </select>
                    </label>
                    <label className="text-sm">出题侧重点
                      <select value={focus} onChange={e => setFocus(e.target.value as typeof focus)} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-2">
                        <option value="comprehensive">综合能力</option><option value="configuration">配置与权限</option><option value="troubleshooting">日志与故障排查</option><option value="architecture">架构、性能与成本</option>
                      </select>
                    </label>
                  </div>
                  <div className="mt-4 rounded-lg bg-slate-900/70 p-3 text-sm text-slate-300">
                    {selectedCaps.length ? `专项测评 · ${selectedCaps.length} 个能力点` : `综合测评 · ${currentService.capabilities?.length || 0} 个候选能力点`} · {questionCount} 题（{questionCount * 2 / 3} 道单选 + {questionCount / 3} 道开放） · {difficultyProfile === "foundation" ? "基础优先" : difficultyProfile === "advanced" ? "进阶优先" : "均衡"}
                    <p className="mt-1 text-xs text-slate-500">近期同服务题干会参与避重；仍可能出现相同考点。不同题量和侧重点的成绩不宜直接横向比较。</p>
                  </div>
                </section>
              )}

              <button
                onClick={startGenerate}
                disabled={!serviceId || !!pending || llmConfigured !== true || !selectedModel || modelsLoading}
                className="w-full py-4 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold rounded-lg transition-colors text-lg"
              >
                {pending ? "🚫 请先完成后测验证" : "🚀 开始生成题目"}
              </button>
            </>
          )}
        </div>
      </main>
    );
  }

  // ---------- Generating ----------
  if (phase === "generating") {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-5xl animate-bounce">🤖</div>
          <div className="text-xl font-semibold">AI 正在为你生成专属题目…</div>
          <p className="text-slate-400">
            正在针对【{currentService?.name}】出题，通常需要 1～3 分钟
          </p>
        </div>
      </main>
    );
  }

  // ---------- Submitting ----------
  if (phase === "submitting") {
    return (
      <main className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-5xl animate-spin-slow">📊</div>
          <div className="text-xl font-semibold">AI 正在多维度评分…</div>
          <p className="text-slate-400">正在逐题评分并生成诊断与学习计划，通常需要 1～3 分钟</p>
        </div>
      </main>
    );
  }

  // ---------- Answering ----------
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 py-10 px-4">
      <div className="sage-content sage-content--reading mx-auto max-w-3xl">
        <header className="mb-8">
          <p className="text-xs font-semibold tracking-[0.2em] text-emerald-400">
            SKILL ASSESSMENT
          </p>
          <div className="mt-2 text-sm text-slate-400">
            {currentService?.icon} {currentService?.name} 测评
          </div>
          <h1 className="sage-page-title mt-2 text-3xl font-bold">答题中</h1>
          <p className="mt-2 text-sm text-slate-400">
            共 {questions.length} 题（{choiceQs.length} 选择 + {openQs.length}{" "}
            开放）· 已答 {answeredCount}/{questions.length}
          </p>
          <div className="mt-3 h-2 bg-slate-800 rounded">
            <div
              className="h-full bg-emerald-500 rounded transition-all"
              style={{ width: `${questions.length > 0 ? (answeredCount / questions.length) * 100 : 0}%` }}
            />
          </div>
        </header>

        {choiceQs.length > 0 && (
          <section className="mb-10">
            <h2 className="text-xl font-semibold mb-4 border-l-4 border-emerald-500 pl-3">
              选择题（{choiceQs.length}）
            </h2>
            <div className="space-y-6">
              {choiceQs.map((q, idx) =>
                q.type === "choice" ? (
                  <div key={q.id} className="bg-slate-800 rounded-lg p-5 border border-slate-700">
                    <div className="flex items-start gap-2 mb-3">
                      <span className="bg-emerald-600 text-white text-xs px-2 py-0.5 rounded">{q.difficulty || "?"}</span>
                      <span className="text-slate-400 text-sm">Q{idx + 1}</span>
                    </div>
                    <p className="text-slate-100 mb-4 leading-relaxed">{q.question}</p>
                    <div className="space-y-2">
                      {q.options.map((opt, optIdx) => {
                        const letter = String.fromCharCode(65 + optIdx);
                        const checked = answers[q.id] === letter;
                        const display = opt.replace(/^[A-Da-d][.、)\s]\s*/, "");
                        return (
                          <label
                            key={optIdx}
                            className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-all border ${
                              checked
                                ? "bg-emerald-500/15 border-emerald-500 ring-1 ring-emerald-500/40"
                                : "bg-slate-900/60 border-slate-700/50 hover:border-slate-500 hover:bg-slate-900"
                            }`}
                          >
                            <span className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold shrink-0 mt-0.5 ${checked ? "bg-emerald-500 text-white" : "bg-slate-700 text-slate-400"}`}>
                              {letter}
                            </span>
                            <input type="radio" name={q.id} value={letter} checked={checked} onChange={(e) => updateAnswer(q.id, e.target.value)} className="sr-only" />
                            <span className={`text-sm leading-relaxed ${checked ? "text-slate-100" : "text-slate-300"}`}>{display}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : null,
              )}
            </div>
          </section>
        )}

        {openQs.length > 0 && (
          <section className="mb-10">
            <h2 className="text-xl font-semibold mb-4 border-l-4 border-amber-500 pl-3">
              开放题（{openQs.length}）
            </h2>
            <div className="space-y-6">
              {openQs.map((q, idx) =>
                q.type === "open" ? (
                  <div key={q.id} className="bg-slate-800 rounded-lg p-5 border border-slate-700">
                    <div className="flex items-start gap-2 mb-3">
                      <span className="bg-amber-600 text-white text-xs px-2 py-0.5 rounded">{q.difficulty || "?"}</span>
                      <span className="text-slate-400 text-sm">Q{idx + 1 + choiceQs.length}</span>
                    </div>
                    <p className="text-slate-100 mb-4 leading-relaxed whitespace-pre-wrap">{q.question}</p>
                    <textarea
                      value={answers[q.id] || ""}
                      onChange={(e) => updateAnswer(q.id, e.target.value)}
                      rows={6}
                      placeholder="请描述你的诊断思路、根因判断和解决方案……"
                      className="w-full bg-slate-900 border border-slate-700 rounded p-3 text-slate-100 text-sm focus:outline-none focus:border-emerald-500"
                    />
                  </div>
                ) : null,
              )}
            </div>
          </section>
        )}

        <div className="sticky bottom-0 bg-slate-900/90 backdrop-blur py-4 -mx-4 px-4 border-t border-slate-700">
          {error && <p className="text-rose-400 text-sm mb-3 text-center">{error}</p>}
          <button
            disabled={!allAnswered}
            onClick={onSubmit}
            className="w-full py-4 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold rounded-lg transition-colors"
          >
            {allAnswered ? "🚀 提交评分" : `还需作答 ${questions.length - answeredCount} 题`}
          </button>
        </div>
      </div>
    </main>
  );
}

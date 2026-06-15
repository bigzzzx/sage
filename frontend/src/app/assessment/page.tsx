"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import {
  fetchPendingPostTest,
  fetchTaxonomy,
  generateQuestions,
  PendingPostTestError,
  submitAssessment,
  type AnswerItem,
  type FullTaxonomy,
  type PendingPostTest,
  type Question,
  type ServiceDef,
} from "@/lib/api";

type Phase = "setup" | "generating" | "answering" | "submitting";

export default function AssessmentPage() {
  const router = useRouter();
  const user = getStoredUser();

  useEffect(() => {
    if (!user) router.push("/login");
    else if (user.role === "manager") router.push("/");
  }, [router]);

  const userProfile = user?.current_profile || "big_data";

  const [phase, setPhase] = useState<Phase>("setup");
  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [trackId, setTrackId] = useState<string>(userProfile);
  const [serviceId, setServiceId] = useState<string>("");
  const [selectedCaps, setSelectedCaps] = useState<string[]>([]);

  const [sessionId, setSessionId] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingPostTest | null>(null);

  useEffect(() => {
    fetchTaxonomy().then(setTaxonomy).catch((e) => setError(String(e)));
  }, []);

  // 选择服务后检查是否有未完成的后测
  useEffect(() => {
    if (!serviceId) {
      setPending(null);
      return;
    }
    fetchPendingPostTest("demo_user", serviceId)
      .then(setPending)
      .catch(() => setPending(null));
  }, [serviceId]);

  const currentTrack = useMemo(
    () => taxonomy?.tracks.find((t) => t.id === trackId),
    [taxonomy, trackId],
  );
  const currentService: ServiceDef | undefined = useMemo(
    () => currentTrack?.services.find((s) => s.id === serviceId),
    [currentTrack, serviceId],
  );

  const toggleCap = (capId: string) => {
    setSelectedCaps((prev) =>
      prev.includes(capId) ? prev.filter((x) => x !== capId) : [...prev, capId],
    );
  };

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
      const result = await submitAssessment("demo_user", items, sessionId);
      sessionStorage.setItem("sage_result", JSON.stringify(result));
      router.push("/result");
    } catch (e) {
      setError(String(e));
      setPhase("answering");
    }
  }

  // ---------- Setup ----------
  if (phase === "setup") {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-3xl font-bold mb-2">🎯 能力测评</h1>
          <p className="text-slate-400 mb-8">
            选择职业方向 → 服务 → 能力点，AI 实时为你出题
          </p>

          {error && <p className="text-rose-400 mb-4">{error}</p>}

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
                      (不选 = 全部)
                    </span>
                  </h2>
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

              {/* 题量说明（固定） */}
              {currentService && !pending && (
                <section className="mb-8">
                  <p className="text-sm text-slate-400">
                    📋 本次测评将生成 <span className="text-emerald-400 font-medium">6 道选择题</span>（L1×2 + L2×2 + L3×2）+{" "}
                    <span className="text-emerald-400 font-medium">3 道开放题</span>（L1×1 + L2×1 + L3×1），由浅入深覆盖全等级。
                  </p>
                </section>
              )}

              <button
                onClick={startGenerate}
                disabled={!serviceId || !!pending}
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
      <main className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-5xl animate-bounce">🤖</div>
          <div className="text-xl font-semibold">AI 正在为你生成专属题目…</div>
          <p className="text-slate-400">
            约 15~30 秒，针对【{currentService?.name}】出题
          </p>
        </div>
      </main>
    );
  }

  // ---------- Submitting ----------
  if (phase === "submitting") {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-5xl animate-spin-slow">📊</div>
          <div className="text-xl font-semibold">AI 正在多维度评分…</div>
          <p className="text-slate-400">每道开放题需要逐一评分，约 30~60 秒</p>
        </div>
      </main>
    );
  }

  // ---------- Answering ----------
  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="max-w-3xl mx-auto">
        <header className="mb-8">
          <div className="text-xs text-emerald-400 mb-1">
            {currentService?.icon} {currentService?.name} 测评
          </div>
          <h1 className="text-3xl font-bold mb-2">🎯 答题中</h1>
          <p className="text-slate-400">
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

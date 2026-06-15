"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import {
  generatePostTest,
  submitPostTest,
  type AnswerItem,
  type Question,
} from "@/lib/api";

type Phase = "generating" | "answering" | "submitting";

export default function PostTestPage() {
  return (
    <Suspense fallback={
      <main className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <p className="text-slate-400">加载中…</p>
      </main>
    }>
      <PostTestInner />
    </Suspense>
  );
}

function PostTestInner() {
  const router = useRouter();

  useEffect(() => {
    if (!getStoredUser()) router.push("/login");
  }, [router]);
  const searchParams = useSearchParams();
  const prevId = searchParams.get("prev") || "";

  const [phase, setPhase] = useState<Phase>("generating");
  const [sessionId, setSessionId] = useState("");
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!prevId) {
      setError("缺少前测 ID，请从结果页进入后测");
      return;
    }
    generatePostTest(prevId)
      .then((resp) => {
        setSessionId(resp.session_id);
        setQuestions(resp.questions);
        setPhase("answering");
      })
      .catch((e) => setError(String(e)));
  }, [prevId]);

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
      const result = await submitPostTest("demo_user", items, sessionId, prevId);
      sessionStorage.setItem("sage_result", JSON.stringify(result));
      router.push("/result");
    } catch (e) {
      setError(String(e));
      setPhase("answering");
    }
  }

  if (error) {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-200 flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-rose-400">{error}</p>
          <a href="/assessment" className="text-emerald-400 underline">
            返回测评
          </a>
        </div>
      </main>
    );
  }

  if (phase === "generating") {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-5xl animate-bounce">📝</div>
          <div className="text-xl font-semibold">正在根据你的薄弱维度生成后测题目…</div>
          <p className="text-slate-400">AI 会针对你之前测评的短板出题，约 15~30 秒</p>
          <div className="flex justify-center gap-1">
            <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse" />
            <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse delay-75" />
            <span className="w-2 h-2 bg-amber-400 rounded-full animate-pulse delay-150" />
          </div>
        </div>
      </main>
    );
  }

  if (phase === "submitting") {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-100 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="text-5xl">📊</div>
          <div className="text-xl font-semibold">AI 正在评分并与前测对比…</div>
          <p className="text-slate-400">评分完成后会展示前后雷达图对比</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="max-w-3xl mx-auto">
        <header className="mb-8">
          <div className="inline-block px-3 py-1 mb-3 text-xs bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-full">
            后测验证
          </div>
          <h1 className="text-3xl font-bold mb-2">📝 后测 — 验证学习成果</h1>
          <p className="text-slate-400">
            题目针对你之前测评中的薄弱维度生成 · 共 {questions.length} 题 · 已答{" "}
            {answeredCount}/{questions.length}
          </p>
          <div className="mt-3 h-2 bg-slate-800 rounded">
            <div
              className="h-full bg-amber-500 rounded transition-all"
              style={{ width: `${questions.length > 0 ? (answeredCount / questions.length) * 100 : 0}%` }}
            />
          </div>
        </header>

        {/* 选择题 */}
        {choiceQs.length > 0 && (
          <section className="mb-10">
            <h2 className="text-xl font-semibold mb-4 border-l-4 border-emerald-500 pl-3">选择题</h2>
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
                          <label key={optIdx} className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-all border ${checked ? "bg-emerald-500/15 border-emerald-500 ring-1 ring-emerald-500/40" : "bg-slate-900/60 border-slate-700/50 hover:border-slate-500 hover:bg-slate-900"}`}>
                            <span className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold shrink-0 mt-0.5 ${checked ? "bg-emerald-500 text-white" : "bg-slate-700 text-slate-400"}`}>{letter}</span>
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

        {/* 开放题 */}
        {openQs.length > 0 && (
          <section className="mb-10">
            <h2 className="text-xl font-semibold mb-4 border-l-4 border-amber-500 pl-3">开放题</h2>
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
                      placeholder="请描述你的诊断思路和解决方案…"
                      className="w-full bg-slate-900 border border-slate-700 rounded p-3 text-slate-100 text-sm focus:outline-none focus:border-amber-500"
                    />
                  </div>
                ) : null,
              )}
            </div>
          </section>
        )}

        <div className="sticky bottom-0 bg-slate-900/90 backdrop-blur py-4 -mx-4 px-4 border-t border-slate-700">
          <button
            disabled={!allAnswered}
            onClick={onSubmit}
            className="w-full py-4 bg-amber-600 hover:bg-amber-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold rounded-lg transition-colors"
          >
            {allAnswered ? "📊 提交后测并查看对比" : `还需作答 ${questions.length - answeredCount} 题`}
          </button>
        </div>
      </div>
    </main>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import {
  fetchPracticeRun, fetchPracticeRuns, fetchPracticeScenarios, inspectPracticeTool,
  startPracticeRun, submitPracticeRun, type PracticeRun, type PracticeRunSummary, type PracticeScenario,
} from "@/lib/api";

function activeRunKey(userId: string) { return `sage_practice_run_${userId}_${getStoredUser()?.current_profile || "unknown"}`; }
function draftKey(runId: string) { return `sage_practice_draft_${runId}`; }

export default function LegacyPracticePage() {
  const router = useRouter();
  const [scenarios, setScenarios] = useState<PracticeScenario[]>([]);
  const [runs, setRuns] = useState<PracticeRunSummary[]>([]);
  const [run, setRun] = useState<PracticeRun | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const user = getStoredUser();
    if (!user) { router.replace("/login"); return; }
    let cancelled = false;
    const savedRunId = localStorage.getItem(activeRunKey(user.user_id));
    Promise.all([fetchPracticeScenarios(), fetchPracticeRuns(), savedRunId ? fetchPracticeRun(savedRunId).catch(() => null) : Promise.resolve(null)])
      .then(([items, previousRuns, previous]) => {
        if (cancelled) return;
        setScenarios(items);
        setRuns(previousRuns);
        if (previous) {
          setRun(previous);
          setAnswer(previous.answer || localStorage.getItem(draftKey(previous.run_id)) || "");
        } else if (savedRunId) localStorage.removeItem(activeRunKey(user.user_id));
      })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [router]);

  async function begin(id: string) {
    const user = getStoredUser();
    if (!user) return;
    setBusy(true); setError("");
    try {
      const next = await startPracticeRun(id);
      localStorage.setItem(activeRunKey(user.user_id), next.run_id);
      setRun(next); setAnswer("");
      fetchPracticeRuns().then(setRuns).catch(() => {});
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function inspect(toolId: string) {
    if (!run) return;
    setBusy(true); setError("");
    try {
      await inspectPracticeTool(run.run_id, toolId);
      setRun(await fetchPracticeRun(run.run_id));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function submit() {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const completed = await submitPracticeRun(run.run_id, answer.trim());
      setRun(completed);
      fetchPracticeRuns().then(setRuns).catch(() => {});
      localStorage.removeItem(draftKey(run.run_id));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function goBack() {
    const user = getStoredUser();
    if (user) localStorage.removeItem(activeRunKey(user.user_id));
    setRun(null); setAnswer(""); setError("");
  }

  async function reopen(runId: string) {
    const user = getStoredUser();
    if (!user) return;
    setBusy(true); setError("");
    try {
      const previous = await fetchPracticeRun(runId);
      localStorage.setItem(activeRunKey(user.user_id), runId);
      setRun(previous);
      setAnswer(previous.answer || localStorage.getItem(draftKey(runId)) || "");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="sage-content mx-auto max-w-6xl px-6 py-12">
        <div className="mb-9 flex items-start justify-between gap-4">
          <div><div className="mb-2 text-xs font-semibold uppercase tracking-[.2em] text-emerald-400">Incident lab</div>
            <h1 className="sage-page-title text-3xl font-bold">经典固定场景练习</h1>
            <p className="sage-page-description mt-3 max-w-2xl text-sm leading-7 text-slate-400">练习排查思路：先查看日志与配置证据，再提交根因、修复和验证方案。当前场景为预设案例，不调用 AI 实时出题；系统按证据和关键词规则给练习反馈，不等同于专家评分。记录保存在你的账户下。</p></div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Link href="/practice" className="rounded-lg border border-emerald-700 px-4 py-2 text-sm text-emerald-300 hover:bg-emerald-950">返回 AI 模拟工单</Link>
            {run && <button onClick={goBack} className="rounded-lg border border-slate-700 px-4 py-2 text-sm hover:bg-slate-800">返回场景</button>}
          </div>
        </div>
        {error && <div role="alert" className="mb-6 rounded-xl border border-rose-700 bg-rose-950/50 p-4 text-sm text-rose-200">{error}</div>}
        {!run ? <><div className="grid gap-5 md:grid-cols-2">
          {scenarios.map(item => <article key={item.id} className="rounded-2xl border border-slate-800 bg-slate-900 p-7 shadow-xl">
            <div className="mb-4 flex items-center gap-2 text-xs"><span className="rounded-full bg-emerald-500/15 px-3 py-1 text-emerald-300">{item.service_id.toUpperCase()}</span><span className="rounded-full bg-slate-800 px-3 py-1 text-slate-300">{item.level}</span></div>
            <h2 className="text-xl font-semibold">{item.title}</h2><p className="mt-3 min-h-20 text-sm leading-7 text-slate-400">{item.brief}</p>
            <button disabled={busy} onClick={() => begin(item.id)} className="mt-6 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold hover:bg-emerald-500 disabled:opacity-50">开始排查 →</button>
          </article>)}
          {!scenarios.length && !error && <p className="text-slate-400">正在加载实战场景…</p>}
        </div>{runs.length > 0 && <section className="mt-12">
          <h2 className="mb-4 text-lg font-semibold">最近练习</h2>
          <div className="grid gap-3 md:grid-cols-2">{runs.map(item => <button key={item.run_id} disabled={busy} onClick={() => reopen(item.run_id)} className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900 p-4 text-left text-sm hover:border-emerald-600 disabled:opacity-50">
            <span>{item.title}<span className="ml-2 text-xs text-slate-500">{item.status === "submitted" ? "已提交" : "进行中"}</span></span>
            <span className="text-emerald-400">{item.score === null ? "继续 →" : `${item.score} 分 →`}</span>
          </button>)}</div>
        </section>}</> : <div className="grid gap-7 lg:grid-cols-[1fr_1fr]">
          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-7">
            <div className="text-xs font-semibold uppercase tracking-widest text-emerald-400">{run.scenario.service_id} · {run.scenario.level}</div>
            <h2 className="mt-3 text-2xl font-semibold">{run.scenario.title}</h2>
            <p className="mt-4 text-sm leading-7 text-slate-300">{run.scenario.brief}</p>
            <div className="mt-7 border-t border-slate-800 pt-6"><h3 className="mb-4 font-semibold">可查看的证据</h3>
              <div className="space-y-3">{run.scenario.tools?.map(tool => <div key={tool.id} className="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
                <div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{tool.label}</span><button disabled={busy || run.status === "submitted"} onClick={() => inspect(tool.id)} className="shrink-0 text-xs font-semibold text-emerald-400 hover:text-emerald-300 disabled:opacity-40">{tool.evidence ? "已查看" : "查看证据"}</button></div>
                {tool.evidence && <p className="mt-3 whitespace-pre-wrap border-t border-slate-800 pt-3 text-sm leading-6 text-slate-300">{tool.evidence}</p>}
              </div>)}</div>
            </div>
          </section>
          <section className="rounded-2xl border border-slate-800 bg-slate-900 p-7">
            <h3 className="text-lg font-semibold">你的排查结论</h3><p className="mt-2 text-sm text-slate-400">{run.scenario.objective}</p>
            <textarea value={answer} onChange={e => { setAnswer(e.target.value); localStorage.setItem(draftKey(run.run_id), e.target.value); }} disabled={run.status === "submitted"} placeholder="证据是什么？根因在哪里？如何修改配置并验证？" className="mt-5 min-h-56 w-full resize-y rounded-xl border border-slate-700 bg-slate-950 p-4 text-sm leading-7 outline-none focus:border-emerald-500 disabled:opacity-70" />
            {run.status !== "submitted" && <button onClick={submit} disabled={busy || answer.trim().length < 20 || !run.inspected_tools.length} className="mt-4 w-full rounded-lg bg-emerald-600 px-5 py-3 text-sm font-semibold hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40">提交排查方案</button>}
            {run.feedback && <div className="mt-7 border-t border-slate-800 pt-6"><div className="flex items-end gap-2"><span className="text-4xl font-bold text-emerald-400">{run.feedback.score}</span><span className="pb-1 text-sm text-slate-400">/ {run.feedback.max_score} · 规则核对分</span></div>
              <div className="mt-5 grid grid-cols-2 gap-2">{run.feedback.checks.map(check => <div key={check.name} className={`rounded-lg p-3 text-sm ${check.passed ? "bg-emerald-900/30 text-emerald-200" : "bg-amber-900/30 text-amber-200"}`}>{check.passed ? "✓" : "○"} {check.name}</div>)}</div>
              <h4 className="mt-6 font-semibold">参考复盘</h4><div className="mt-3 space-y-3 text-sm leading-7 text-slate-300"><p><span className="text-slate-500">根因：</span>{run.feedback.reference.root_cause}</p><p><span className="text-slate-500">修复：</span>{run.feedback.reference.remediation}</p><p><span className="text-slate-500">验证：</span>{run.feedback.reference.verification}</p></div>
              <p className="mt-5 text-xs text-slate-500">{run.feedback.note}</p>
            </div>}
          </section>
        </div>}
      </div>
    </main>
  );
}

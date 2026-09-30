"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import LearningPlanCard from "@/components/LearningPlanCard";
import { fetchAssessmentResult, type AssessmentResult } from "@/lib/api";

export default function PlanDetailPage() {
  const router = useRouter();
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!getStoredUser()) { router.replace("/login"); return; }
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) { queueMicrotask(() => setError("缺少学习计划编号")); return; }
    let cancelled = false;
    fetchAssessmentResult(id).then(value => {
      if (!cancelled) setResult(value);
    }).catch(reason => { if (!cancelled) setError((reason as Error).message); });
    return () => { cancelled = true; };
  }, [router]);

  const plan = result?.learning_plan;
  return <main className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100">
    <div className="sage-content sage-content--reading mx-auto max-w-5xl">
      <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
        <div><p className="text-xs font-semibold uppercase tracking-widest text-emerald-400">Learning plan</p>
          <h1 className="sage-page-title mt-2 text-3xl font-bold">{plan?.plan_name || "学习计划详情"}</h1>
          {result && <p className="mt-2 text-sm text-slate-400">{result.service_name} · 来源：{result.kind === "post" ? "后测" : "前测"}</p>}</div>
        <div className="flex gap-4 text-sm"><Link href="/history?tab=plans" className="text-slate-400 hover:text-emerald-300">← 全部计划</Link>
          {result && <Link href={`/result?id=${encodeURIComponent(result.assessment_id || "")}`} className="text-emerald-300 hover:underline">查看对应测评 →</Link>}</div>
      </div>
      {error ? <p role="alert" className="rounded-xl border border-rose-800 bg-rose-950/30 p-5 text-rose-200">{error}</p>
        : !result ? <p className="py-16 text-center text-slate-400">正在读取学习计划…</p>
          : !plan ? <p className="rounded-xl border border-slate-800 p-6 text-slate-400">这次测评没有生成学习计划。</p>
            : <>
              <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/60 p-5">
                <p className={result.plan_review?.status === "passed" ? "text-sm text-emerald-300" : "text-sm text-amber-300"}>
                  {result.plan_review?.status === "passed" ? "自动流程检查通过；技术内容仍需人工核验" : "计划待复核，资源变更类任务请勿直接照做"}
                </p>
                {!!result.plan_review?.remaining_issues?.length && <ul className="mt-3 list-inside list-disc space-y-2 text-sm text-slate-300">
                  {result.plan_review.remaining_issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
              </section>
              <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 md:p-7">
                <LearningPlanCard plan={plan} gaps={result.diagnosis || []}
                  assessmentId={result.plan_review?.status === "passed" ? result.assessment_id : undefined}
                  showOverallAssessment={!!result.rating_reliable} />
              </section>
            </>}
    </div>
  </main>;
}

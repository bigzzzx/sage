"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser, type UserInfo } from "@/lib/auth";
import { fetchActivePlans, fetchArchive, fetchLlmStatus, fetchTicketArchive,
  type ActivePlan, type ArchiveItem, type TicketSummary } from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [plans, setPlans] = useState<ActivePlan[]>([]);
  const [history, setHistory] = useState<ArchiveItem[]>([]);
  const [recentPlans, setRecentPlans] = useState<ArchiveItem[]>([]);
  const [runs, setRuns] = useState<TicketSummary[]>([]);
  const [totals, setTotals] = useState({ plans: 0, assessments: 0, tickets: 0 });
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    const stored = getStoredUser();
    if (!stored) {
      router.push("/login");
      return;
    }
    queueMicrotask(() => setUser(stored));
  }, [router]);

  const userId = user?.user_id;
  const profile = user?.current_profile;
  const role = user?.role;
  useEffect(() => {
    if (!userId || role === "manager") return;
    let cancelled = false;
    fetchActivePlans(userId, profile || "big_data").then(value => { if (!cancelled) setPlans(value); }).catch(() => {});
    fetchArchive(userId, "plans", 0, 2).then(value => { if (!cancelled) { setRecentPlans(value.items); setTotals(old => ({ ...old, plans: value.total })); } }).catch(() => {});
    fetchArchive(userId, "assessments", 0, 2).then(value => { if (!cancelled) { setHistory(value.items); setTotals(old => ({ ...old, assessments: value.total })); } }).catch(() => {});
    fetchTicketArchive(0, 2).then(value => { if (!cancelled) { setRuns(value.items); setTotals(old => ({ ...old, tickets: value.total })); } }).catch(() => {});
    fetchLlmStatus().then(value => { if (!cancelled) setLlmConfigured(value.configured); }).catch(() => {});
    return () => { cancelled = true; };
  }, [userId, profile, role]);

  if (!user) return null;

  return (
    <main className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800 text-slate-100 flex flex-col">
      <div className="sage-content mx-auto w-full max-w-6xl flex-1 px-6 py-12 md:py-16">
        <div className="mb-11 flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="mb-3 text-xs font-semibold uppercase tracking-[.22em] text-emerald-400">SE Adaptive Growth Engine</p>
            <h1 className="sage-page-title text-3xl font-bold tracking-tight md:text-5xl">你好，{user.display_name || user.username}</h1>
            <p className="sage-page-description mt-4 max-w-2xl text-sm leading-7 text-slate-400">{user.role === "manager" ? "查看团队能力分布，识别培训优先级。" : "这里是你的学习工作台：开始 AI 测评、查看学习计划，或与模拟客户对话处理工单。"}</p>
          </div>
          {user.role !== "manager" && <span className={`rounded-full border px-4 py-2 text-xs ${llmConfigured === true ? "border-emerald-700 bg-emerald-950/50 text-emerald-300" : "border-amber-700 bg-amber-950/50 text-amber-300"}`}>{llmConfigured === true ? "模型参数已配置" : llmConfigured === false ? "AI 测评待配置" : "正在检查模型配置"}</span>}
        </div>

        {user.role === "manager" ? <Link href="/dashboard" className="block max-w-2xl rounded-2xl border border-emerald-800 bg-gradient-to-br from-emerald-950/70 to-slate-900 p-8 shadow-xl hover:border-emerald-500">
          <p className="text-xs font-semibold uppercase tracking-widest text-emerald-400">Team insight</p>
          <h2 className="mt-3 text-2xl font-semibold">团队能力看板</h2>
          <p className="mt-3 text-sm leading-7 text-slate-300">查看各成员已测服务、能力分布与团队短板。数据只向管理员开放。</p>
          <span className="mt-7 inline-block text-sm font-semibold text-emerald-300">进入看板 →</span>
        </Link> : <>
          <div className="mb-8 grid gap-4 sm:grid-cols-3">
            {[
              { label: "学习计划", value: totals.plans, unit: "份", href: "/history?tab=plans", detail: `当前方向 ${plans.length} 份进行中` },
              { label: "历史测评", value: totals.assessments, unit: "次", href: "/history?tab=assessments", detail: "查看全部报告" },
              { label: "模拟工单", value: totals.tickets, unit: "次", href: "/history?tab=tickets", detail: "查看全部工单" },
            ].map(item => <Link key={item.label} href={item.href} className="group rounded-2xl border border-slate-800 bg-slate-900/70 p-6 transition-colors hover:border-emerald-600 focus-visible:outline-2 focus-visible:outline-emerald-400">
              <p className="text-xs text-slate-400">{item.label}</p><p className="mt-3 text-3xl font-semibold">{item.value}<span className="ml-2 text-sm font-normal text-slate-500">{item.unit}</span></p>
              <p className="mt-3 text-xs text-emerald-300">{item.detail} →</p>
            </Link>)}
          </div>

          <div className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
            <Link href="/practice" className="group rounded-2xl border border-emerald-800/70 bg-gradient-to-br from-emerald-950/60 via-slate-900 to-slate-900 p-8 shadow-xl hover:border-emerald-500">
              <span className="rounded-full bg-emerald-500/15 px-3 py-1 text-xs font-semibold text-emerald-300">AI 客户模拟 · 多轮对话</span>
              <h2 className="mt-5 text-2xl font-semibold">实战工单</h2>
              <p className="mt-3 max-w-md text-sm leading-7 text-slate-300">从当前 Profile 选择 AWS 服务、7 类工单和不同客户画像，向模拟客户追问证据，提交解决方案并获得六维复盘报告。</p>
              <span className="mt-9 inline-block text-sm font-semibold text-emerald-300 group-hover:translate-x-1 transition-transform">进入工单 →</span>
            </Link>
            <div className="grid gap-6">
              <Link href="/assessment" className="rounded-2xl border border-slate-800 bg-slate-900/80 p-6 hover:border-slate-600">
                <span className="text-xs font-semibold text-sky-400">01 / 能力定位</span>
                <h2 className="mt-2 text-lg font-semibold">AI 能力测评</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">按所选题量评估知识与排障能力，再生成个性化计划。{llmConfigured === false ? "目前需管理员配置模型。" : ""}</p>
              </Link>
              <Link href="/profile" className="rounded-2xl border border-slate-800 bg-slate-900/80 p-6 hover:border-slate-600">
                <span className="text-xs font-semibold text-amber-400">02 / 学习跟进</span>
                <h2 className="mt-2 text-lg font-semibold">我的能力档案</h2>
                <p className="mt-2 text-sm leading-6 text-slate-400">回看报告、跟踪学习任务，并提交实验与复盘证据。</p>
              </Link>
            </div>
          </div>

          <div className="mt-10 grid gap-6 lg:grid-cols-3">
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"><div className="mb-4 flex items-center justify-between gap-2"><h2 className="font-semibold">最近学习计划</h2><Link href="/history?tab=plans" className="text-xs text-emerald-300 hover:underline">查看全部 →</Link></div>
              {recentPlans.length ? <div className="space-y-3">{recentPlans.map(plan => <Link key={plan.assessment_id} href={`/history/plan?id=${plan.assessment_id}`} className="block rounded-xl border border-slate-800 bg-slate-950/50 p-4 hover:border-emerald-700"><span className="text-sm font-medium">{plan.service_id}</span><p className="mt-1 line-clamp-2 text-xs text-slate-400">{plan.plan_name} · {plan.status === "completed" ? "已归档" : "进行中"}</p></Link>)}</div> : <p className="text-sm text-slate-500">暂无学习计划。完成 AI 前测后会显示在这里。</p>}
            </section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"><div className="mb-4 flex items-center justify-between gap-2"><h2 className="font-semibold">最近测评</h2><Link href="/history?tab=assessments" className="text-xs text-emerald-300 hover:underline">查看全部 →</Link></div>
              {history.length ? <div className="space-y-3">{history.map(item => <Link key={item.assessment_id} href={`/result?id=${item.assessment_id}`} className="flex justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950/50 p-4 text-sm hover:border-emerald-700"><span>{item.service_id} · {item.kind === "post" ? "后测" : "前测"}</span><span className="shrink-0 text-emerald-400">{item.rating_reliable ? item.overall_level : "样本不足"} →</span></Link>)}</div> : <p className="text-sm text-slate-500">暂无测评报告。</p>}
            </section>
            <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6"><div className="mb-4 flex items-center justify-between gap-2"><h2 className="font-semibold">最近工单</h2><Link href="/history?tab=tickets" className="text-xs text-emerald-300 hover:underline">查看全部 →</Link></div>
              {runs.length ? <div className="space-y-3">{runs.map(item => <Link key={item.ticket_id} href={`/practice?ticket=${item.ticket_id}`} className="block rounded-xl border border-slate-800 bg-slate-950/50 p-4 text-sm hover:border-emerald-700"><span className="line-clamp-2">{item.title}</span><span className="mt-1 block text-xs text-emerald-400">{item.status === "closed" ? `${item.overall_score ?? "—"} 分` : "处理中"} →</span></Link>)}</div> : <p className="text-sm text-slate-500">暂无模拟工单。</p>}
            </section>
          </div>
        </>}
      </div>
    </main>
  );
}

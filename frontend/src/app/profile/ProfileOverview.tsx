"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import TrackRadarChart from "@/components/TrackRadarChart";
import MyTrainingAssignments from "@/components/MyTrainingAssignments";
import MyQualityFeedback from "@/components/MyQualityFeedback";
import { fetchProfileInsights, type ProfileInsights, type UserServiceScore } from "@/lib/api";

const day = (value: string) => value ? new Date(value).toLocaleDateString("zh-CN") : "";

export default function ProfileOverview() {
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getStoredUser>>(null);
  const [insights, setInsights] = useState<ProfileInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const stored = getStoredUser();
    queueMicrotask(() => setUser(stored));
    if (!stored) { router.replace("/login"); return; }
    if (stored.role === "manager") { router.replace("/"); return; }
    let cancelled = false;
    fetchProfileInsights(stored.user_id).then(data => {
      if (!cancelled) { setInsights(data); setLoading(false); }
    }).catch(reason => {
      if (!cancelled) { setError((reason as Error).message); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [router]);

  const reliableServices = useMemo<UserServiceScore[]>(() => (insights?.services || [])
    .filter(s => s.latest_assessment?.rating_reliable)
    .map(s => ({ service_id: s.service_id, service_name: s.service_name,
      icon: s.icon, score: s.latest_assessment!.score!, is_tested: true,
      rating_reliable: true, is_real: true, capabilities: [],
      last_assessed_at: s.latest_assessment!.created_at })), [insights]);
  const tested = insights?.services.filter(s => s.latest_assessment).length || 0;
  const covered = insights?.services.reduce((n, s) => n + s.tested_capability_count, 0) || 0;
  const total = insights?.services.reduce((n, s) => n + s.capabilities.length, 0) || 0;
  const plan = insights?.plans[0];
  const untested = insights?.services.find(s => !s.latest_assessment);
  const ticketPriority = insights?.ticket_dimensions.filter(d => d.score !== null)
    .sort((a, b) => (a.score ?? 0) - (b.score ?? 0))[0];

  return <main className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100"><div className="sage-content mx-auto max-w-6xl space-y-7">
    <header className="flex flex-wrap items-start justify-between gap-4"><div>
      <p className="text-xs font-semibold tracking-[0.2em] text-emerald-400">LEARNING PROFILE</p>
      <h1 className="sage-page-title mt-2 text-3xl font-bold">我的能力档案</h1>
      <p className="sage-page-description mt-2 text-sm text-slate-400">{user?.display_name || "当前用户"} · {insights?.profile_name || user?.current_profile || ""} · 只显示当前 Profile 的学习证据</p>
    </div><Link href="/assessment" className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium hover:bg-emerald-500">开始新测评 →</Link></header>
    {loading && <p className="rounded-xl border border-slate-800 p-8 text-center text-slate-400">档案加载中…</p>}
    {error && <p role="alert" className="rounded-xl border border-rose-800 p-5 text-rose-300">{error}</p>}
    {insights && <>
      <MyTrainingAssignments />
      <MyQualityFeedback />
      <section className="space-y-4"><div className="flex items-center justify-between gap-2"><div><h2 className="text-xl font-semibold">能力概览</h2><p className="mt-1 text-xs text-slate-400">学习证据覆盖情况，不是职业能力总分。</p></div><Link href="/history" className="text-sm text-emerald-300 hover:underline">全部历史 →</Link></div>
        <div className="grid gap-3 sm:grid-cols-3"><Metric label="已测服务" value={`${tested} / ${insights.services.length}`} detail="至少完成过一次测评" href="/history?tab=assessments" /><Metric label="有答题证据的能力点" value={`${covered} / ${total}`} detail="未测能力点不计为 0 分" href="/assessment" /><Metric label="已结案模拟工单" value={`${insights.ticket_count}`} detail="与知识测评分开展示" href="/history?tab=tickets" /></div>
      </section>
      <section className="rounded-xl border border-emerald-900/70 bg-emerald-950/20 p-5"><h2 className="text-lg font-semibold">下一步可以做什么</h2><div className="mt-3 grid gap-3 md:grid-cols-3">
        <Action title={plan ? `${plan.review_status === "passed" ? "继续" : "查看待复核的"} ${plan.service_name} 学习计划` : "开始一份学习计划"} detail={plan ? (plan.review_status === "passed" ? `已记录 ${plan.completed_tasks}/${plan.total_tasks} 项任务` : "先看复核问题，暂不建议直接执行") : "先完成测评，再查看复核后的计划"} href={plan ? `/history/plan?id=${plan.assessment_id}` : "/assessment"} />
        <Action title={untested ? `探索 ${untested.service_name}` : "复盘历史测评"} detail={untested ? "暂无答题证据，不代表能力为零" : "查看报告中的证据与改进项"} href={untested ? "/assessment" : "/history?tab=assessments"} />
        <Action title={ticketPriority ? `练习：${ticketPriority.label}` : "练习客户工单沟通"} detail="仅依据模拟工单的 AI 教学反馈" href="/practice" />
      </div></section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><SectionHead title="进行中的学习计划" href="/history?tab=plans" link="全部计划" />
        {insights.plans.length === 0 ? <p className="mt-4 text-sm text-slate-400">暂无进行中的计划。</p> : <div className="mt-4 grid gap-3 md:grid-cols-2">{insights.plans.slice(0, 2).map(p => <div key={p.assessment_id} className="rounded-lg border border-slate-700 bg-slate-950/60 p-4">
          <div className="flex items-center justify-between gap-2"><p className="font-medium">{p.service_name}</p><span className="text-xs text-slate-400">{p.completed_tasks}/{p.total_tasks} 项已记录</span></div><p className="mt-1 truncate text-sm text-slate-400" title={p.plan_name}>{p.plan_name}</p>
          <div className="mt-3 h-2 rounded-full bg-slate-800" role="progressbar" aria-label={`${p.service_name} 学习计划进度`} aria-valuenow={p.completed_tasks} aria-valuemin={0} aria-valuemax={p.total_tasks || 1}><div className="h-full rounded-full bg-emerald-500" style={{ width: `${p.total_tasks ? Math.min(100, 100 * p.completed_tasks / p.total_tasks) : 0}%` }} /></div>
          <div className="mt-3 flex items-center justify-between"><span className="text-xs text-slate-500">{p.review_status === "passed" ? "计划已复核" : "计划待复核，不建议直接执行"}</span><Link href={`/history/plan?id=${p.assessment_id}`} className="text-sm text-emerald-300 hover:underline">查看计划 →</Link></div>
        </div>)}</div>}
      </section>
      <section className="space-y-4"><div><h2 className="text-xl font-semibold">服务与能力点</h2><p className="mt-1 text-xs text-slate-400">能力点取最近一次覆盖它的答题记录；标注样本数，不跨测评取平均。</p></div>
        {insights.services.map(s => <details key={s.service_id} className="rounded-xl border border-slate-800 bg-slate-900" open={s.service_id === insights.services.find(item => item.latest_assessment)?.service_id}><summary className="cursor-pointer list-none p-5"><div className="flex flex-wrap items-center justify-between gap-2"><div><span className="mr-2">{s.icon}</span><span className="font-semibold">{s.service_name}</span><span className="ml-3 text-xs text-slate-400">{s.tested_capability_count}/{s.capabilities.length} 个能力点有证据</span></div><span className="text-sm text-slate-300">{s.latest_assessment ? (s.latest_assessment.score === null ? "暂无有效评分" : `最近一次 ${s.latest_assessment.score}/5 · ${s.latest_assessment.question_count} 题${s.latest_assessment.rating_reliable ? "" : " · 样本不足，暂不定级"}`) : "未测评"}</span></div></summary>
          <div className="border-t border-slate-800 px-5 pb-5 pt-4">{s.latest_assessment && <p className="mb-3 text-xs text-slate-500">最近测评 {day(s.latest_assessment.created_at)} · <Link href={`/result?id=${s.latest_assessment.id}`} className="text-emerald-300 hover:underline">完整报告</Link></p>}
            <div className="grid gap-2 md:grid-cols-2">{s.capabilities.map(c => <div key={c.id} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3"><div className="flex items-start justify-between gap-2"><span className="text-sm font-medium">{c.name}</span><span className="shrink-0 text-sm text-emerald-300">{c.score === null ? "未测" : `${c.score}/5`}</span></div>
              {c.score !== null && <><div className="mt-2 h-1.5 rounded-full bg-slate-800"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.max(0, Math.min(100, c.score * 20))}%` }} /></div><div className="mt-2 flex items-center justify-between text-xs text-slate-500"><span>{c.sample_count} 道题 · {c.sample_count < 2 ? "仅供参考" : "最近覆盖"} · {day(c.assessed_at)}</span>{c.assessment_id && <Link href={`/result?id=${c.assessment_id}`} className="text-emerald-300 hover:underline">证据 →</Link>}</div></>}
            </div>)}</div>
          </div></details>)}
      </section>
      {reliableServices.length >= 3 && <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="text-lg font-semibold">跨服务概览</h2><p className="mt-1 text-xs text-slate-400">仅显示最近测评样本足够的服务；不同测评范围的分数不用于排名。</p><TrackRadarChart data={reliableServices} height={350} /></section>}
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><SectionHead title="模拟工单表现" href="/history?tab=tickets" link="全部工单" /><p className="mt-1 text-xs text-slate-400">仅汇总当前 Profile、同一评分版本、已结案且有观察证据的 AI 教学评分；不是 AWS 实际支持能力认证。</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3">{insights.ticket_dimensions.map(d => <div key={d.id} className="rounded-lg border border-slate-700 bg-slate-950/60 p-4"><div className="flex justify-between gap-2"><h3 className="text-sm font-medium">{d.label}</h3><span className="text-emerald-300">{d.score === null ? "暂无观察" : `${d.score}/5`}</span></div><p className="mt-2 text-xs text-slate-400">{d.sample_count} 个有效工单样本</p>{d.next_step && <p className="mt-2 line-clamp-2 text-xs text-slate-400" title={d.next_step}>下次练习：{d.next_step}</p>}{d.latest_ticket_id && <Link href={`/practice?ticket=${d.latest_ticket_id}`} className="mt-3 inline-block text-xs text-emerald-300 hover:underline">查看评分依据 →</Link>}</div>)}</div>
      </section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><h2 className="text-lg font-semibold">前后测成长记录</h2><p className="mt-1 text-xs text-slate-400">关联前后测的样本、评分版本、覆盖范围和题目均可比，才显示分数变化；同题练习的变化也不等于真实工作能力提升。</p>
        {insights.trends.length === 0 ? <p className="mt-4 text-sm text-slate-400">暂无已完成的前后测组合。</p> : <div className="mt-4 space-y-3">{insights.trends.slice(0, 3).map(t => <div key={t.post_assessment_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-700 bg-slate-950/60 p-4"><div><p className="font-medium">{insights.services.find(s => s.service_id === t.service_id)?.service_name || t.service_id} · {day(t.created_at)}</p><p className="mt-1 text-xs text-slate-400">前测 {t.pre_score}/5（{t.pre_count} 题） · 后测 {t.post_score}/5（{t.post_count} 题）</p><p className={`mt-2 text-xs ${t.comparable ? "text-emerald-300" : "text-amber-300"}`}>{t.comparable ? `可比样本：${(t.delta ?? 0) >= 0 ? "+" : ""}${t.delta} / 5` : `不计算成长幅度：${t.reason}`}</p></div><div className="flex gap-3 text-xs"><Link href={`/result?id=${t.pre_assessment_id}`} className="text-emerald-300 hover:underline">前测报告</Link><Link href={`/result?id=${t.post_assessment_id}`} className="text-emerald-300 hover:underline">后测报告</Link></div></div>)}</div>}
      </section>
      <section className="rounded-xl border border-slate-800 bg-slate-900 p-5"><SectionHead title="最近报告" href="/history?tab=assessments" link="全部测评" /><div className="mt-3 grid gap-2 sm:grid-cols-3">{insights.recent_assessments.length ? insights.recent_assessments.map(a => <Link key={a.assessment_id} href={`/result?id=${a.assessment_id}`} className="rounded-lg border border-slate-700 bg-slate-950/60 p-3 text-sm hover:border-emerald-600">{insights.services.find(s => s.service_id === a.service_id)?.service_name || a.service_id} · {a.kind === "post" ? "后测" : "前测"}{a.record_origin === "agent_test" && <span className="ml-2 text-amber-300">代答测试</span>}<span className="mt-1 block text-xs text-slate-500">{day(a.created_at)} · 查看报告 →</span></Link>) : <p className="text-sm text-slate-400">暂无测评报告。</p>}</div></section>
    </>}
  </div></main>;
}

function Metric({ label, value, detail, href }: { label: string; value: string; detail: string; href: string }) {
  return <Link href={href} className="rounded-xl border border-slate-800 bg-slate-900 p-5 hover:border-emerald-700"><p className="text-xs text-slate-400">{label}</p><p className="mt-2 text-2xl font-bold text-emerald-300">{value}</p><p className="mt-1 text-xs text-slate-500">{detail}</p></Link>;
}

function Action({ title, detail, href }: { title: string; detail: string; href: string }) {
  return <Link href={href} className="rounded-lg border border-emerald-900/60 bg-slate-950/60 p-4 hover:border-emerald-500"><p className="text-sm font-semibold text-emerald-200">{title} →</p><p className="mt-1 text-xs text-slate-400">{detail}</p></Link>;
}

function SectionHead({ title, href, link }: { title: string; href: string; link: string }) {
  return <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">{title}</h2><Link href={href} className="text-sm text-emerald-300 hover:underline">{link} →</Link></div>;
}

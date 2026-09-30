"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { fetchManagerRecord, fetchTeamMemberDetail, type ManagerRecord, type TeamMemberDetail } from "@/lib/api";
import DiagnosisPanel from "@/components/DiagnosisPanel";
import LearningPlanCard from "@/components/LearningPlanCard";

export default function MemberDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = String(params.id || "");
  const [detail, setDetail] = useState<TeamMemberDetail | null>(null);
  const [record, setRecord] = useState<ManagerRecord | null>(null);
  const [error, setError] = useState("");
  const [profile, setProfile] = useState("");
  useEffect(() => {
    const user = getStoredUser();
    if (!user || user.role !== "manager") { router.replace("/admin/login"); return; }
    const requested = new URLSearchParams(window.location.search).get("profile");
    queueMicrotask(() => setProfile(requested && ["big_data", "analytics", "networking"].includes(requested)
      ? requested : user.current_profile || "big_data"));
  }, [router]);
  useEffect(() => {
    if (!profile || !id) return;
    fetchTeamMemberDetail(id, profile).then(setDetail).catch(reason => setError(reason instanceof Error ? reason.message : "读取失败"));
  }, [id, profile]);
  async function open(kind: "assessments" | "tickets", recordId: string) {
    try { setRecord(await fetchManagerRecord(id, kind, recordId, profile)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "读取记录失败"); }
  }
  useEffect(() => {
    if (!detail || !profile) return;
    const query = new URLSearchParams(window.location.search);
    const kind = query.get("kind");
    const recordId = query.get("record");
    if (!recordId || !["assessments", "tickets"].includes(kind || "")) return;
    const ids = kind === "assessments" ? detail.assessments.map(item => item.id) : detail.tickets.map(item => item.id);
    if (!ids.includes(recordId)) return;
    fetchManagerRecord(id, kind as "assessments" | "tickets", recordId, profile)
      .then(setRecord).catch(reason => setError(String(reason)));
  }, [detail, id, profile]);
  return <main className="min-h-screen bg-slate-900 px-4 py-10 text-slate-100"><div className="sage-content mx-auto max-w-5xl space-y-6">
    <Link href="/dashboard" className="text-sm text-emerald-300">← 团队看板</Link>
    <h1 className="text-3xl font-bold">{detail?.member.display_name || detail?.member.username || "成员明细"}</h1>
    <p className="text-sm text-slate-400">{profile} 方向 · 只读查看。测评和工单使用各自的评分体系，不做跨类型平均。</p>
    {error && <p role="alert" className="text-rose-300">{error}</p>}
    {!detail && !error && <p className="text-slate-400">加载中…</p>}
    {detail && <div className="grid gap-5 md:grid-cols-2">
      <section className="rounded-xl border border-slate-700 bg-slate-800 p-5"><h2 className="text-lg font-semibold">测评与学习计划</h2><div className="mt-4 space-y-2">{detail.assessments.map(item => <button key={item.id} onClick={() => void open("assessments", item.id)} className="block w-full rounded border border-slate-700 bg-slate-950 p-3 text-left text-sm hover:border-emerald-500">{item.service_id} · {item.kind === "post" ? "学后测" : "前测"} · {item.score}/5 {item.rating_reliable ? "" : "（参考）"}<br/><span className="text-xs text-slate-400">{item.question_count} 题 · {new Date(item.created_at).toLocaleDateString("zh-CN")} {item.has_plan ? "· 有计划" : ""}</span></button>)}{detail.assessments.length === 0 && <p className="text-sm text-slate-400">暂无测评</p>}</div></section>
      <section className="rounded-xl border border-slate-700 bg-slate-800 p-5"><h2 className="text-lg font-semibold">实战工单</h2><div className="mt-4 space-y-2">{detail.tickets.map(item => <button key={item.id} onClick={() => void open("tickets", item.id)} className="block w-full rounded border border-slate-700 bg-slate-950 p-3 text-left text-sm hover:border-emerald-500">{item.service_id} · {item.category} · {item.status}<br/><span className="text-xs text-slate-400">{new Date(item.created_at).toLocaleDateString("zh-CN")}</span></button>)}{detail.tickets.length === 0 && <p className="text-sm text-slate-400">暂无工单</p>}</div></section>
    </div>}
    {record && <section className="space-y-5"><div className="flex items-center justify-between"><h2 className="text-xl font-semibold">{record.service_id} · {record.record_type === "assessment" ? "测评详情" : "工单详情"}</h2><button onClick={() => setRecord(null)} className="text-sm text-slate-400">关闭</button></div>
      {record.record_type === "assessment" ? <>
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-5"><p className="text-2xl font-bold text-emerald-300">{record.summary.overall_avg}/5 <span className="text-sm font-normal text-slate-400">{record.summary.rating_reliable ? record.summary.overall_level : "参考分 · 暂不定级"}</span></p><p className="mt-2 text-sm text-slate-300">{record.summary.question_count} 题 · {record.summary.rating_reason}</p></div>
        <DiagnosisPanel gaps={record.diagnosis} />
        {record.learning_plan && <LearningPlanCard plan={record.learning_plan} gaps={record.diagnosis} showOverallAssessment={false} />}
        {record.plan_review.remaining_issues?.length ? <div className="rounded-xl border border-amber-800 p-5 text-sm text-amber-200">计划待核查：{record.plan_review.remaining_issues.join("；")}</div> : null}
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-5"><h3 className="font-semibold">答题反馈</h3><div className="mt-3 space-y-2">{record.question_results.map((item, index) => <div key={`${item.question_id}-${index}`} className="rounded bg-slate-950 p-3 text-sm"><span className="text-emerald-300">第 {index + 1} 题 · {item.total_score}/5</span><p className="mt-1 text-slate-300">{item.feedback}</p></div>)}</div></div>
      </> : <>
        <div className="rounded-xl border border-slate-700 bg-slate-800 p-5"><h3 className="font-semibold">客户对话</h3><div className="mt-4 space-y-3">{record.messages.map((item, index) => <p key={index} className={`max-w-[85%] rounded-xl p-3 text-sm whitespace-pre-wrap ${item.role === "user" ? "ml-auto bg-emerald-950" : "bg-slate-950"}`}><span className="block pb-1 text-xs text-slate-400">{item.role === "user" ? "技术支持" : "客户"}</span>{item.content}</p>)}</div></div>
        {"overall_score" in record.report && <div className="rounded-xl border border-slate-700 bg-slate-800 p-5"><h3 className="text-lg font-semibold">工单复盘 <span className="text-emerald-300">{record.report.overall_score}/100</span></h3><p className="mt-2 text-sm text-slate-300">{record.report.summary}</p><div className="mt-4 grid gap-3 sm:grid-cols-2">{record.report.dimensions.map(item => <div key={item.id} className="rounded-lg bg-slate-950 p-4"><p className="font-medium">{item.label} · {item.not_observed ? "未观察" : `${item.score}/${item.max_score}`}</p><p className="mt-2 text-sm text-slate-300">{item.reason}</p></div>)}</div></div>}
      </>}
    </section>}
  </div></main>;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { fetchQualityFeedback, reviewQualityFeedback, type QualityFeedback } from "@/lib/api";

export default function FeedbackReviewPage() {
  const router = useRouter();
  const [items, setItems] = useState<QualityFeedback[]>([]);
  const [filter, setFilter] = useState("open");
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  useEffect(() => {
    if (getStoredUser()?.role !== "manager") { router.replace("/admin/login"); return; }
    fetchQualityFeedback().then(setItems).catch(reason => setError(String(reason)));
  }, [router]);
  const shown = items.filter(item => filter === "all" || item.status === filter);
  return <main className="mx-auto max-w-6xl px-6 py-10 text-slate-100">
    <h1 className="text-3xl font-bold">纠错与质量复核</h1>
    <p className="mt-2 text-sm text-slate-400">这里保留用户指出问题时的原始评分/案例快照。接受反馈只记录复核结果，不会偷偷修改历史成绩；修正题库或知识库需另行处理。</p>
    <div className="mt-6 flex gap-3 text-sm">{["open", "needs_info", "accepted", "rejected", "all"].map(value =>
      <button key={value} type="button" onClick={() => setFilter(value)} className={`rounded-lg px-3 py-2 ${filter === value ? "bg-emerald-700" : "bg-slate-800"}`}>
        {{ open: "待复核", needs_info: "待补充", accepted: "已采纳", rejected: "未采纳", all: "全部" }[value as "open" | "needs_info" | "accepted" | "rejected" | "all"]}
      </button>)}</div>
    {error && <p role="alert" className="mt-4 text-rose-300">{error}</p>}
    <div className="mt-5 space-y-4">{shown.map(item => <article key={item.id} className="rounded-xl border border-slate-700 bg-slate-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-400"><span>{item.profile_id} · {item.record_type === "assessment" ? "测评" : "工单"} · {item.category} · {item.status} · 用户 {item.user_id}</span><span>{new Date(item.created_at).toLocaleString()}</span></div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{item.description}</p>
      <p className="mt-2 text-xs text-slate-400">原记录：<Link className="text-sky-300 hover:underline" href={`/dashboard/members/${encodeURIComponent(item.user_id)}?profile=${encodeURIComponent(item.profile_id)}&kind=${item.record_type === "assessment" ? "assessments" : "tickets"}&record=${encodeURIComponent(item.record_id)}`}>{item.record_id}</Link>{item.question_id ? ` · 题目 ${item.question_id}` : ""}</p>
      <details className="mt-3 text-xs text-slate-400"><summary className="cursor-pointer">查看提交时的原始快照</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3">{JSON.stringify(item.original_snapshot, null, 2)}</pre></details>
      {item.review_note && <p className="mt-3 rounded-lg bg-slate-950 p-3 text-sm text-emerald-200">复核意见：{item.review_note}</p>}
      <textarea value={notes[item.id] ?? ""} onChange={event => setNotes(previous => ({ ...previous, [item.id]: event.target.value }))}
        placeholder="复核依据与下一步处理（至少 10 字）" rows={2} className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm" />
      <div className="mt-2 flex flex-wrap gap-2">{(["accepted", "rejected", "needs_info"] as const).map(status => <button key={status} type="button"
        disabled={busyId === item.id || (notes[item.id] || "").trim().length < 10}
        onClick={async () => { setBusyId(item.id); setError(""); try { const updated = await reviewQualityFeedback(item.id, status, (notes[item.id] || "").trim()); setItems(previous => previous.map(old => old.id === updated.id ? updated : old)); } catch (reason) { setError(String(reason)); } finally { setBusyId(""); } }}
        className="rounded-lg border border-slate-600 px-3 py-2 text-xs hover:border-emerald-500 disabled:opacity-40">{status === "accepted" ? "采纳" : status === "rejected" ? "不采纳" : "需补充"}</button>)}</div>
    </article>)}{!shown.length && <p className="text-sm text-slate-400">当前筛选条件下没有反馈。</p>}</div>
  </main>;
}

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { fetchLearningReviewQueue, fetchTaxonomy, reviewLearningProgress,
  type FullTaxonomy, type LearningReviewItem } from "@/lib/api";

export default function LearningReviewPage() {
  const router = useRouter();
  const [profile, setProfile] = useState("big_data");
  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [items, setItems] = useState<LearningReviewItem[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  useEffect(() => {
    const user = getStoredUser();
    if (user?.role !== "manager") { router.replace("/admin/login"); return; }
    queueMicrotask(() => setProfile(user.current_profile || "big_data"));
    fetchTaxonomy().then(setTaxonomy).catch(reason => setError(String(reason)));
  }, [router]);
  useEffect(() => { fetchLearningReviewQueue(profile).then(setItems).catch(reason => setError(String(reason))); }, [profile]);
  return <main className="mx-auto max-w-5xl px-6 py-10 text-slate-100">
    <h1 className="text-3xl font-bold">学习证据验收</h1>
    <p className="mt-2 text-sm text-slate-400">用户提交不等于通过；管理员核对实际产出后再标记已验收。当前队列仅显示所选 Profile 的待验收任务。</p>
    <label className="mt-5 block text-sm">方向 <select value={profile} onChange={event => setProfile(event.target.value)} className="ml-2 rounded-lg border border-slate-700 bg-slate-900 p-2">{(taxonomy?.tracks || [{ id: profile, name: profile }]).map(track => <option key={track.id} value={track.id}>{track.name}</option>)}</select></label>
    {error && <p role="alert" className="mt-4 text-rose-300">{error}</p>}
    <div className="mt-5 space-y-4">{items.map(item => <article key={item.id} className="rounded-xl border border-slate-700 bg-slate-900 p-5">
      <p className="text-xs text-slate-400">用户 {item.user_id} · {item.service_id} · 第 {item.week_index + 1} 周第 {item.task_index + 1} 项</p>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-6">{item.evidence}</p>
      <textarea value={notes[item.id] || ""} onChange={event => setNotes(previous => ({ ...previous, [item.id]: event.target.value }))} rows={2} placeholder="说明证据是否满足任务验收条件（至少 10 字）" className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm" />
      <div className="mt-2 flex gap-2">{[true, false].map(accepted => <button key={String(accepted)} type="button" disabled={busyId === item.id || (notes[item.id] || "").trim().length < 10} onClick={async () => {
        setBusyId(item.id); setError("");
        try { await reviewLearningProgress(item.id, accepted, notes[item.id].trim()); setItems(previous => previous.filter(old => old.id !== item.id)); }
        catch (reason) { setError(String(reason)); } finally { setBusyId(""); }
      }} className="rounded-lg border border-slate-600 px-4 py-2 text-xs hover:border-emerald-500 disabled:opacity-40">{accepted ? "验收通过" : "退回补充"}</button>)}</div>
    </article>)}{items.length === 0 && <p className="text-sm text-slate-400">暂无待验收证据。</p>}</div>
  </main>;
}

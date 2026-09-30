"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { fetchTicket, saveKnowledgeEntry, type TicketSession } from "@/lib/api";

const FIELDS = [["symptom", "客户现象"], ["investigation", "排查过程"],
  ["root_cause", "问题根因"], ["resolution", "解决方案"], ["verification", "验证方式"]] as const;
const errorText = (value: unknown) => value instanceof Error ? value.message : "提交失败";

export default function ContributeCasePage() {
  const router = useRouter();
  const [ticket, setTicket] = useState<TicketSession | null>(null);
  const [title, setTitle] = useState("");
  const [details, setDetails] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!getStoredUser()) { router.replace("/login"); return; }
    const id = new URLSearchParams(window.location.search).get("ticket");
    if (!id) { queueMicrotask(() => setError("缺少工单编号")); return; }
    fetchTicket(id).then(item => {
      if (item.status !== "closed" || !item.report) { setError("只能从已结案工单投稿"); return; }
      setTicket(item); setTitle(item.title);
      setDetails({ symptom: item.report.problem,
        investigation: item.report.reference.investigation_steps?.join("\n") || item.report.reference.reasoning || "",
        root_cause: item.report.reference.root_cause,
        resolution: item.report.reference.resolution,
        verification: item.report.reference.verification });
    }).catch(reason => setError(errorText(reason)));
  }, [router]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!ticket) return;
    const user = getStoredUser(); if (!user?.current_profile) return;
    setSaving(true); setError(""); setNotice("");
    try {
      await saveKnowledgeEntry({ profile_id: user.current_profile, service_id: ticket.service_id,
        capability_id: "", source_type: "case", title: title.trim(), url: "",
        details, source_ticket_id: ticket.ticket_id });
      setNotice("已提交审核。此教学案例不会自动进入知识库；管理员核查并发布后才可检索。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setSaving(false); }
  }
  return <main className="min-h-screen bg-slate-950 px-5 py-10 text-slate-100"><div className="mx-auto max-w-3xl space-y-5">
    <Link href={ticket ? `/practice?ticket=${encodeURIComponent(ticket.ticket_id)}` : "/practice"} className="text-sm text-sky-300">← 返回工单</Link>
    <h1 className="text-3xl font-bold">提交教学案例建议</h1>
    <p className="rounded-xl border border-amber-800/70 bg-amber-950/20 p-4 text-sm leading-6 text-amber-200">这是一份模拟工单，不是真实客户故障。下面仅预填复盘报告，可能含 AI 推测；请逐项核对、删除敏感信息，不要把未验证结论写成事实。投稿须经管理员审核，不能作为 AWS 官方依据。</p>
    {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-700 p-3 text-sm text-emerald-300">{notice}</p>}
    {ticket && !notice && <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <p className="text-sm text-slate-400">服务：{ticket.service_id} · 关联模拟工单：{ticket.ticket_id}</p>
      <label className="block text-sm">标题<input required minLength={4} maxLength={160} value={title} onChange={e => setTitle(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5" /></label>
      {FIELDS.map(([key, label]) => <label key={key} className="block text-sm">{label}<textarea required maxLength={4000} rows={4} value={details[key] || ""} onChange={e => setDetails({ ...details, [key]: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5" /></label>)}
      <button type="submit" disabled={saving} className="rounded-lg bg-emerald-700 px-5 py-2.5 text-sm font-semibold disabled:opacity-50">{saving ? "提交中…" : "提交管理员审核"}</button>
    </form>}
  </div></main>;
}

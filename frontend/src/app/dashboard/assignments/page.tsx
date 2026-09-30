"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { createAssignment, fetchAdminAccounts, fetchAssignments, fetchEnrollments, fetchTaxonomy,
  type AdminAccount, type FullTaxonomy, type TrainingAssignment } from "@/lib/api";

export default function TrainingAssignmentsPage() {
  const router = useRouter();
  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [accounts, setAccounts] = useState<AdminAccount[]>([]);
  const [enrolled, setEnrolled] = useState<string[]>([]);
  const [profile, setProfile] = useState("big_data");
  const [userId, setUserId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [capabilityId, setCapabilityId] = useState("");
  const [kind, setKind] = useState<"assessment" | "ticket">("assessment");
  const [count, setCount] = useState(12);
  const [difficulty, setDifficulty] = useState("balanced");
  const [focus, setFocus] = useState<TrainingAssignment["focus"]>("comprehensive");
  const [due, setDue] = useState("");
  const [note, setNote] = useState("");
  const [items, setItems] = useState<TrainingAssignment[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const user = getStoredUser();
    if (user?.role !== "manager") { router.replace("/admin/login"); return; }
    queueMicrotask(() => setProfile(user.current_profile || "big_data"));
    Promise.all([fetchTaxonomy(), fetchAdminAccounts()]).then(([tax, users]) => { setTaxonomy(tax); setAccounts(users); }).catch(reason => setError(String(reason)));
  }, [router]);
  useEffect(() => {
    Promise.all([fetchAssignments(profile), fetchEnrollments(profile)]).then(([assignments, ids]) => {
      setItems(assignments); setEnrolled(ids);
    }).catch(reason => setError(String(reason)));
  }, [profile]);
  const services = taxonomy?.tracks.find(item => item.id === profile)?.services || [];
  const effectiveService = services.find(item => item.id === serviceId) || services[0];
  const members = accounts.filter(item => item.role === "member" && item.is_active && enrolled.includes(item.user_id));
  const effectiveUser = members.find(item => item.user_id === userId) || members[0];
  return <main className="mx-auto max-w-6xl px-6 py-10 text-slate-100">
    <h1 className="text-3xl font-bold">团队培训任务</h1>
    <p className="mt-2 text-sm text-slate-400">只向该 Profile 培训名单中的成员布置。测评任务固定服务、能力点、题量、难度、侧重点和评分版本；完成状态由布置后产生的符合条件的记录计算，不能手工勾选。</p>
    {error && <p role="alert" className="mt-4 text-rose-300">{error}</p>}{notice && <p role="status" className="mt-4 text-emerald-300">{notice}</p>}
    <section className="mt-6 rounded-xl border border-slate-700 bg-slate-900 p-5">
      <h2 className="font-semibold">布置新任务</h2>
      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">Profile<select value={profile} onChange={event => { setProfile(event.target.value); setServiceId(""); setUserId(""); }} className="mt-1 w-full rounded-lg bg-slate-950 p-2">{taxonomy?.tracks.map(track => <option key={track.id} value={track.id}>{track.name}</option>)}</select></label>
        <label className="text-sm">成员<select value={effectiveUser?.user_id || ""} onChange={event => setUserId(event.target.value)} className="mt-1 w-full rounded-lg bg-slate-950 p-2">{members.map(item => <option key={item.user_id} value={item.user_id}>{item.display_name || item.username}</option>)}</select></label>
        <label className="text-sm">服务<select value={effectiveService?.id || ""} onChange={event => { setServiceId(event.target.value); setCapabilityId(""); }} className="mt-1 w-full rounded-lg bg-slate-950 p-2">{services.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-sm">类型<select value={kind} onChange={event => { setKind(event.target.value as "assessment" | "ticket"); setCapabilityId(""); }} className="mt-1 w-full rounded-lg bg-slate-950 p-2"><option value="assessment">能力测评</option><option value="ticket">模拟工单</option></select></label>
        {kind === "assessment" && <><label className="text-sm">能力点<select value={capabilityId} onChange={event => setCapabilityId(event.target.value)} className="mt-1 w-full rounded-lg bg-slate-950 p-2"><option value="">综合测评</option>{effectiveService?.capabilities?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="text-sm">题量<select value={count} onChange={event => setCount(Number(event.target.value))} className="mt-1 w-full rounded-lg bg-slate-950 p-2"><option value={6}>6</option><option value={12}>12</option><option value={18}>18</option></select></label>
          <label className="text-sm">难度<select value={difficulty} onChange={event => setDifficulty(event.target.value)} className="mt-1 w-full rounded-lg bg-slate-950 p-2"><option value="foundation">基础优先</option><option value="balanced">均衡</option><option value="advanced">进阶优先</option></select></label></>}
        {kind === "assessment" && <label className="text-sm">题目侧重点<select value={focus} onChange={event => setFocus(event.target.value as TrainingAssignment["focus"])} className="mt-1 w-full rounded-lg bg-slate-950 p-2"><option value="comprehensive">综合</option><option value="configuration">配置实践</option><option value="troubleshooting">故障排查</option><option value="architecture">架构设计</option></select></label>}
        <label className="text-sm">截止时间<input type="datetime-local" value={due} onChange={event => setDue(event.target.value)} className="mt-1 w-full rounded-lg bg-slate-950 p-2" /></label>
      </div>
      <label className="mt-4 block text-sm">任务说明<textarea value={note} onChange={event => setNote(event.target.value)} maxLength={500} rows={2} className="mt-1 w-full rounded-lg bg-slate-950 p-3" /></label>
      {!members.length && <p className="mt-3 text-xs text-amber-300">当前方向暂无已启用的培训成员。请先去账号管理维护培训名单。</p>}
      <button type="button" disabled={busy || !effectiveUser || !effectiveService} onClick={async () => {
        setBusy(true); setError(""); setNotice("");
        try { await createAssignment({ user_id: effectiveUser.user_id, profile_id: profile, service_id: effectiveService.id,
          kind, capability_id: kind === "assessment" ? capabilityId : "", question_count: count,
          difficulty_profile: difficulty, focus, note, due_at: due ? new Date(due).toISOString() : null });
          setItems(await fetchAssignments(profile)); setNotice("任务已布置，成员可在个人档案看到。");
        } catch (reason) { setError(String(reason)); } finally { setBusy(false); }
      }} className="mt-4 rounded-lg bg-emerald-700 px-5 py-2 text-sm disabled:opacity-40">{busy ? "保存中…" : "布置任务"}</button>
    </section>
    <section className="mt-6 space-y-3"><h2 className="text-lg font-semibold">任务记录</h2>{items.map(item => <div key={item.id} className="rounded-xl border border-slate-700 bg-slate-900 p-4 text-sm"><div className="flex flex-wrap justify-between gap-2"><span>{accounts.find(user => user.user_id === item.user_id)?.display_name || item.user_id} · {item.service_id} · {item.kind === "assessment" ? `${item.question_count} 题测评 · ${item.focus} · ${item.scoring_version}` : "模拟工单"}</span><span className={item.status === "overdue" ? "text-rose-300" : "text-emerald-300"}>{item.status === "completed" ? "已完成" : item.status === "overdue" ? "已逾期" : "待完成"}</span></div><p className="mt-2 text-xs text-slate-400">{item.note || "无补充说明"}{item.due_at ? ` · 截止 ${new Date(item.due_at).toLocaleString()}` : ""}{item.evidence_id ? ` · 证据 ${item.evidence_id}` : ""}</p></div>)}{!items.length && <p className="text-sm text-slate-400">暂无培训任务。</p>}</section>
  </main>;
}

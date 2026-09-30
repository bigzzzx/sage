"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchAssignments, type TrainingAssignment } from "@/lib/api";

export default function MyTrainingAssignments() {
  const [items, setItems] = useState<TrainingAssignment[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { fetchAssignments().then(setItems).catch(reason => setError(String(reason))); }, []);
  return <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
    <h2 className="text-lg font-semibold">管理员布置的培训任务</h2>
    <p className="mt-1 text-xs text-slate-400">仅当前 Profile；完成状态依据布置后生成的同服务、同配置测评或已结案工单，不把其他练习混算。</p>
    {error && <p role="alert" className="mt-3 text-rose-300">{error}</p>}
    <div className="mt-4 grid gap-3 md:grid-cols-2">{items.slice(0, 6).map(item => {
      const query = new URLSearchParams({ service: item.service_id });
      if (item.capability_id) query.set("capability", item.capability_id);
      if (item.kind === "assessment") { query.set("count", String(item.question_count)); query.set("difficulty", item.difficulty_profile); query.set("focus", item.focus); query.set("assignment", item.id); }
      const href = item.status === "completed" ? item.kind === "assessment" ? `/result?id=${item.evidence_id}` : `/practice?ticket=${item.evidence_id}`
        : item.kind === "assessment" ? `/assessment?${query}` : `/practice?${query}`;
      return <Link key={item.id} href={href} className="rounded-lg border border-slate-700 bg-slate-950 p-4 text-sm hover:border-emerald-600">
        <div className="flex justify-between gap-3"><span className="font-medium">{item.service_id} · {item.kind === "assessment" ? `${item.question_count} 题测评` : "模拟工单"}</span><span className={item.status === "overdue" ? "text-rose-300" : "text-emerald-300"}>{item.status === "completed" ? "已完成" : item.status === "overdue" ? "已逾期" : "待完成"}</span></div>
        {item.note && <p className="mt-2 line-clamp-2 text-xs text-slate-400">{item.note}</p>}
        <p className="mt-2 text-xs text-slate-500">{item.due_at ? `截止 ${new Date(item.due_at).toLocaleString()} · ` : ""}{item.status === "completed" ? "查看证据" : "开始任务"} →</p>
      </Link>;
    })}{!items.length && !error && <p className="text-sm text-slate-400">暂无培训任务。</p>}</div>
  </section>;
}

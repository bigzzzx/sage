"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { fetchOperationMetrics, fetchTaxonomy, type FullTaxonomy, type OperationMetrics } from "@/lib/api";

export default function OperationsPage() {
  const router = useRouter();
  const [profile, setProfile] = useState("big_data");
  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [report, setReport] = useState<OperationMetrics | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const user = getStoredUser();
    if (user?.role !== "manager") { router.replace("/admin/login"); return; }
    queueMicrotask(() => setProfile(user.current_profile || "big_data"));
    fetchTaxonomy().then(setTaxonomy).catch(reason => setError(String(reason)));
  }, [router]);
  useEffect(() => { fetchOperationMetrics(profile, days).then(setReport).catch(reason => setError(String(reason))); }, [profile, days]);
  return <main className="mx-auto max-w-6xl px-6 py-10 text-slate-100">
    <h1 className="text-3xl font-bold">运行质量与成本</h1>
    <p className="mt-2 text-sm text-slate-400">按真实后台任务记录聚合。成功率与耗时是系统运行指标，不代表题目或评分质量；质量问题请在纠错复核页查看。</p>
    <div className="mt-5 flex flex-wrap gap-3 text-sm"><label>Profile <select value={profile} onChange={event => setProfile(event.target.value)} className="ml-2 rounded-lg bg-slate-900 p-2">{(taxonomy?.tracks || [{ id: profile, name: profile }]).map(track => <option key={track.id} value={track.id}>{track.name}</option>)}</select></label>
      <label>时间范围 <select value={days} onChange={event => setDays(Number(event.target.value) as 7 | 30 | 90)} className="ml-2 rounded-lg bg-slate-900 p-2"><option value={7}>近 7 天</option><option value={30}>近 30 天</option><option value={90}>近 90 天</option></select></label></div>
    {error && <p role="alert" className="mt-4 text-rose-300">{error}</p>}
    {report && <><div className="mt-6 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-slate-900 p-5"><p className="text-xs text-slate-400">任务样本</p><p className="mt-2 text-2xl text-emerald-300">{report.sample_count}</p></div><div className="rounded-xl bg-slate-900 p-5"><p className="text-xs text-slate-400">估算费用</p><p className="mt-2 text-2xl text-emerald-300">{report.estimated_usd === null ? "未知" : `$${report.estimated_usd.toFixed(4)}`}</p></div><div className="rounded-xl bg-slate-900 p-5"><p className="text-xs text-slate-400">未标价调用 / 无用量历史任务</p><p className="mt-2 text-2xl text-amber-300">{report.unpriced_calls} / {report.unobserved_tasks}</p></div></div>
      {report.truncated && <p className="mt-3 text-xs text-amber-300">样本超过 5000 条，当前仅展示最近 5000 条。</p>}
      <section className="mt-6 overflow-x-auto rounded-xl border border-slate-700 bg-slate-900 p-5"><h2 className="font-semibold">任务可靠性与耗时</h2><table className="mt-4 w-full min-w-[620px] text-left text-sm"><thead className="text-slate-400"><tr><th className="pb-3">类型</th><th>总数</th><th>成功</th><th>失败</th><th>运行中</th><th>P50</th><th>P95</th></tr></thead><tbody>{report.by_kind.map(item => <tr key={item.kind} className="border-t border-slate-800"><td className="py-3">{item.kind}</td><td>{item.total}</td><td>{item.done}</td><td>{item.error}</td><td>{item.pending}</td><td>{item.p50_ms === null ? "—" : `${(item.p50_ms / 1000).toFixed(1)}s`}</td><td>{item.p95_ms === null ? "—" : `${(item.p95_ms / 1000).toFixed(1)}s`}</td></tr>)}</tbody></table>{!report.by_kind.length && <p className="text-sm text-slate-400">当前范围无任务记录。</p>}</section>
      <section className="mt-6 rounded-xl border border-slate-700 bg-slate-900 p-5"><h2 className="font-semibold">模型调用与 Token</h2><div className="mt-3 grid gap-3 md:grid-cols-2">{Object.entries(report.by_model).map(([model, item]) => <div key={model} className="rounded-lg bg-slate-950 p-4 text-sm"><p className="font-medium">{model}</p><p className="mt-2 text-slate-400">{item.calls} 次调用 · 失败 {item.failed} · 输入 {item.prompt_tokens} token · 输出 {item.completion_tokens} token · 用量缺失 {item.token_usage_missing}</p></div>)}{!Object.keys(report.by_model).length && <p className="text-sm text-slate-400">历史任务没有采集模型用量；新任务完成后才会显示。</p>}</div></section>
      <p className="mt-4 text-xs leading-6 text-slate-400">{report.note}</p></>}
  </main>;
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { fetchArchive, fetchTicketArchive, fetchTaxonomy, type ArchiveItem, type TicketSummary } from "@/lib/api";

type Tab = "plans" | "assessments" | "tickets";
const PAGE_SIZE = 12;
const TABS: { id: Tab; label: string }[] = [
  { id: "plans", label: "学习计划" },
  { id: "assessments", label: "能力测评" },
  { id: "tickets", label: "模拟工单" },
];

function validTab(value: string | null): Tab {
  return value === "assessments" || value === "tickets" ? value : "plans";
}

function dateLabel(value: string) {
  return value ? new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }) : "";
}

export default function HistoryPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("plans");
  const [ready, setReady] = useState(false);
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<(ArchiveItem | TicketSummary)[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [service, setService] = useState("");
  const [state, setState] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [services, setServices] = useState<{ id: string; name: string }[]>([]);

  useEffect(() => {
    if (!getStoredUser()) { router.replace("/login"); return; }
    queueMicrotask(() => {
      setTab(validTab(new URLSearchParams(window.location.search).get("tab")));
      setReady(true);
    });
    fetchTaxonomy().then(data => setServices(data.tracks.find(track => track.id === getStoredUser()?.current_profile)?.services || [])).catch(() => {});
  }, [router]);

  useEffect(() => {
    if (!ready) return;
    const user = getStoredUser();
    if (!user || user.role === "manager") { router.replace("/"); return; }
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) { setLoading(true); setError(""); } });
    const request = tab === "tickets" ? fetchTicketArchive(offset, PAGE_SIZE, { service_id: service, status: state, q: query })
      : fetchArchive(user.user_id, tab, offset, PAGE_SIZE, { service_id: service, state, q: query });
    request.then(page => {
      if (!cancelled) { setItems(page.items); setTotal(page.total); setLoading(false); }
    }).catch(reason => {
      if (!cancelled) { setError((reason as Error).message); setLoading(false); }
    });
    return () => { cancelled = true; };
  }, [ready, tab, offset, router, service, state, query]);

  function choose(next: Tab) {
    setTab(next); setOffset(0); setItems([]); setTotal(0); setState("");
    window.history.replaceState(null, "", `/history?tab=${next}`);
  }

  return <main className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100">
    <div className="sage-content sage-content--reading mx-auto max-w-5xl">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-xs font-semibold uppercase tracking-widest text-emerald-400">Archive</p>
          <h1 className="sage-page-title mt-2 text-3xl font-bold">我的历史记录</h1>
          <p className="sage-page-description mt-2 text-sm text-slate-400">当前 Profile：{ready ? getStoredUser()?.current_profile || "—" : "—"}。这里只显示该方向的学习计划、测评报告和模拟工单；切换方向后可查看另一组记录。</p></div>
        <Link href="/" className="text-sm text-slate-400 hover:text-emerald-300">← 返回首页</Link>
      </div>
      <nav aria-label="历史记录类别" className="mb-6 flex gap-2 border-b border-slate-800 pb-3">
        {TABS.map(item => <button key={item.id} type="button" onClick={() => choose(item.id)}
          aria-current={tab === item.id ? "page" : undefined}
          className={`rounded-lg px-4 py-2 text-sm ${tab === item.id ? "bg-emerald-700 text-white" : "text-slate-400 hover:bg-slate-800 hover:text-white"}`}>
          {item.label}</button>)}
      </nav>
      <div className="mb-5 grid gap-3 rounded-xl border border-slate-800 bg-slate-900 p-4 sm:grid-cols-3">
        <label className="text-xs text-slate-400">服务<select value={service} onChange={event => { setService(event.target.value); setOffset(0); }} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-white"><option value="">全部服务</option>{services.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="text-xs text-slate-400">状态<select value={state} onChange={event => { setState(event.target.value); setOffset(0); }} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-white"><option value="">全部状态</option>{tab === "tickets" ? <><option value="open">处理中</option><option value="closed">已结案</option></> : tab === "plans" ? <option value="active">进行中</option> : <><option value="pre">前测</option><option value="post">后测</option></>}</select></label>
        <form onSubmit={event => { event.preventDefault(); setQuery(search.trim()); setOffset(0); }} className="flex items-end gap-2"><label className="flex-1 text-xs text-slate-400">搜索<input value={search} onChange={event => setSearch(event.target.value)} maxLength={80} placeholder="服务、标题或记录 ID" className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2 text-sm text-white" /></label><button className="rounded-lg bg-emerald-700 px-3 py-2 text-xs text-white">搜索</button></form>
      </div>
      <div className="mb-4 flex items-center justify-between text-sm text-slate-400"><span>共 {total} 条</span><span>每页 {PAGE_SIZE} 条</span></div>
      {error && <p role="alert" className="rounded-lg border border-rose-800 bg-rose-950/30 p-4 text-rose-200">加载失败：{error}</p>}
      {loading ? <p className="py-16 text-center text-slate-400">正在加载历史记录…</p>
        : !items.length ? <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-10 text-center text-slate-400">暂无{TABS.find(item => item.id === tab)?.label}记录。</div>
          : <div className="space-y-3">{items.map(item => {
            if (tab === "tickets") {
              const ticket = item as TicketSummary;
              return <Link key={ticket.ticket_id} href={`/practice?ticket=${encodeURIComponent(ticket.ticket_id)}`}
                className="flex items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5 hover:border-emerald-600">
                <div className="min-w-0"><p className="font-medium">{ticket.title}</p><p className="mt-2 text-xs text-slate-400">{ticket.category_label} · {dateLabel(ticket.created_at)} · {ticket.status === "closed" ? "已结案" : "处理中"}</p></div>
                <span className="shrink-0 text-sm text-emerald-300">{ticket.overall_score === null ? "查看 / 继续" : `${ticket.overall_score} 分`} →</span>
              </Link>;
            }
            const record = item as ArchiveItem;
            return <Link key={record.assessment_id} href={tab === "plans" ? `/history/plan?id=${encodeURIComponent(record.assessment_id)}` : `/result?id=${encodeURIComponent(record.assessment_id)}`}
              className="flex items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 p-5 hover:border-emerald-600">
              <div className="min-w-0"><p className="truncate font-medium">{tab === "plans" ? record.plan_name || "学习计划" : `${record.service_id} · ${record.kind === "post" ? "后测" : "前测"}`} {record.record_origin === "agent_test" && <span className="ml-2 text-amber-300">代答测试</span>}</p>
                <p className="mt-2 text-xs text-slate-400">{record.service_id} · {dateLabel(record.created_at)}{tab === "plans" ? ` · ${record.status === "completed" ? "已归档" : "进行中"}${record.review_status === "passed" ? "" : " · 待复核"}` : ` · ${record.rating_reliable ? record.overall_level : "样本不足，暂不定级"}`}</p></div>
              <span className="shrink-0 text-sm text-emerald-300">查看详情 →</span>
            </Link>;
          })}</div>}
      {total > PAGE_SIZE && <div className="mt-7 flex items-center justify-center gap-4 text-sm">
        <button type="button" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))} className="rounded-lg border border-slate-700 px-4 py-2 disabled:opacity-40">上一页</button>
        <span className="text-slate-400">第 {Math.floor(offset / PAGE_SIZE) + 1} / {Math.ceil(total / PAGE_SIZE)} 页</span>
        <button type="button" disabled={loading || offset + PAGE_SIZE >= total} onClick={() => setOffset(value => value + PAGE_SIZE)} className="rounded-lg border border-slate-700 px-4 py-2 disabled:opacity-40">下一页</button>
      </div>}
    </div>
  </main>;
}

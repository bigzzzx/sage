"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import QualityFeedbackForm from "@/components/QualityFeedbackForm";
import {
  fetchLlmModels, fetchTicket, fetchTicketOptions, fetchTickets, finishTicket,
  sendTicketMessage, startTicket, hasPendingTicketJob, resumeTicketJob, type LlmModels, type TicketOptions,
  type TicketReport, type TicketSession, type TicketSummary,
} from "@/lib/api";

function activeTicketKey(userId: string) { return `sage_active_ticket_${userId}_${getStoredUser()?.current_profile || "unknown"}`; }
function draftKey(ticketId: string) { return `sage_ticket_draft_${getStoredUser()?.user_id}_${ticketId}`; }

function Report({ report }: { report: TicketReport }) {
  return <section className="w-full rounded-2xl border border-emerald-700/50 bg-slate-900 p-5 md:p-7">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[.2em] text-emerald-400">实战小助手 · 工单复盘</p>
        <h2 className="mt-2 text-2xl font-bold">本次处理报告</h2>
        <p className="mt-2 max-w-3xl text-sm leading-7 text-slate-300">{report.summary}</p>
      </div>
      <div className="rounded-xl border border-emerald-800 bg-emerald-950/40 px-5 py-3 text-center">
        <div className="text-3xl font-bold text-emerald-300">{report.overall_score}</div>
        <div className="text-xs text-slate-400">/ 100 · AI 教学分</div>
        {report.critical_gap && <p className="mt-1 max-w-32 text-xs text-amber-300">关键技术或方案项待改进</p>}
      </div>
    </div>

    <div className="mt-7 grid gap-4 md:grid-cols-2">
      {report.dimensions.map(item => <div key={item.id} className="rounded-xl border border-slate-700 bg-slate-950/60 p-5">
        <div className="flex items-center justify-between gap-4">
          <h3 className="font-semibold text-slate-100">{item.label}</h3>
          <p className="shrink-0 text-xl font-semibold text-emerald-300">{item.not_observed ? "未观察" : item.score}<span className="text-sm font-normal text-slate-500">{item.not_observed ? "" : ` / ${item.max_score}`}</span></p>
        </div>
        {!!item.weight && <p className="mt-1 text-xs text-slate-500">综合权重 {item.weight}%{item.not_observed ? " · 不计入本次总分" : ""}</p>}
        <p className="mt-3 text-sm leading-7 text-slate-300">{item.reason}</p>
        {item.next_step && <div className="mt-4 rounded-lg bg-emerald-950/35 p-3 text-sm leading-6 text-emerald-200"><span className="font-semibold">下次建议：</span>{item.next_step}</div>}
        {!!item.citations?.length && <details className="mt-4 border-t border-slate-800 pt-3">
          <summary className="cursor-pointer text-xs text-sky-400">查看评分依据（{item.citations.length} 条原文）</summary>
          {item.citations.map((citation, index) => <blockquote key={index} className="mt-3 border-l-2 border-slate-600 pl-3 text-xs leading-6 text-slate-400">
            <span className="text-sky-400">{citation.role === "final" ? "结案方案" : `第 ${citation.turn} 轮 · ${citation.role === "user" ? "你的回复" : "客户回复"}`}</span>
            <p>“{citation.quote}”</p>
          </blockquote>)}
        </details>}
      </div>)}
    </div>

    <div className="mt-7 grid gap-5 lg:grid-cols-2">
      <div className="rounded-xl border border-slate-700 bg-slate-950/50 p-5">
        <h3 className="font-semibold text-sky-300">问题与参考处理</h3>
        <dl className="mt-3 space-y-3 text-sm leading-6 text-slate-300">
          {report.reference.background && <div><dt className="text-slate-500">业务背景</dt><dd>{report.reference.background}</dd></div>}
          {report.reference.scenario && <div><dt className="text-slate-500">固定场景</dt><dd>{report.reference.scenario}</dd></div>}
          <div><dt className="text-slate-500">客户问题</dt><dd>{report.problem}</dd></div>
          {report.reference.reasoning && <div><dt className="text-slate-500">参考诊断思路</dt><dd>{report.reference.reasoning}</dd></div>}
          <div><dt className="text-slate-500">参考根因或配置要点</dt><dd>{report.reference.root_cause}</dd></div>
          <div><dt className="text-slate-500">参考方案</dt><dd>{report.reference.resolution}</dd></div>
          <div><dt className="text-slate-500">验证闭环</dt><dd>{report.reference.verification}</dd></div>
        </dl>
      </div>
      <div className="rounded-xl border border-slate-700 bg-slate-950/50 p-5">
        <h3 className="font-semibold text-sky-300">你的回答与排查路径</h3>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-300">{report.user_answer}</p>
        {!!report.reference.investigation_steps?.length && <><p className="mt-4 text-xs text-slate-500">创建工单时已冻结的参考排查路径</p>
          <ol className="mt-2 list-inside list-decimal space-y-2 text-sm text-slate-300">{report.reference.investigation_steps.map((step, index) => <li key={index}>{step}</li>)}</ol></>}
        {report.investigation_steps.length > 0 && <ol className="mt-4 list-inside list-decimal space-y-2 text-sm text-slate-300">
          {report.investigation_steps.map((step, index) => <li key={index}>{step}</li>)}
        </ol>}
      </div>
    </div>

    <div className="mt-5 grid gap-5 md:grid-cols-2">
      <div className="rounded-xl border border-emerald-800/60 bg-emerald-950/20 p-5"><h3 className="font-semibold text-emerald-300">做得好的地方</h3>
        <ul className="mt-3 list-inside list-disc space-y-2 text-sm leading-6 text-slate-300">{report.strengths.length ? report.strengths.map((item, index) => <li key={index}>{item}</li>) : <li>暂无可确认的优势，请结合对话复盘。</li>}</ul>
      </div>
      <div className="rounded-xl border border-amber-800/60 bg-amber-950/20 p-5"><h3 className="font-semibold text-amber-300">下一次可以改进</h3>
        <ul className="mt-3 list-inside list-disc space-y-2 text-sm leading-6 text-slate-300">{report.improvements.length ? report.improvements.map((item, index) => <li key={index}>{item}</li>) : <li>建议再检查证据、方案和验证是否闭环。</li>}</ul>
      </div>
    </div>
    <p className="mt-5 text-xs leading-6 text-slate-500">{report.note}</p>
    {!!report.pending_actions?.length && <div className="mt-4 rounded-lg border border-amber-800 p-4 text-sm text-amber-200">
      <p className="font-semibold">尚未确认完成的操作</p>
      <ul className="mt-2 list-inside list-disc">{report.pending_actions.map((action, index) =>
        <li key={index}>第 {action.turn} 轮 · {action.text}（{action.status}）</li>)}</ul>
    </div>}
    {!!report.source_records?.length && <details className="mt-4 text-xs text-slate-400">
      <summary className="cursor-pointer">查看结论与参考资料的对应关系</summary>
      {report.claim_basis?.map(basis => <div key={basis.field} className="mt-3">
        <p className="text-slate-200">{basis.field === "root_cause" ? "技术判断" : "处理方案"} · 案例证据：{basis.evidence_ids.join("、")}</p>
        {basis.source_ids.map(id => {
          const source = report.source_records?.find(item => item.id === id);
          return source ? <a key={id} href={source.url} target="_blank" rel="noopener noreferrer" className="mr-3 text-sky-400 hover:underline">{id} ↗</a> : null;
        })}
      </div>)}
    </details>}
    {report.sources.length > 0 && <div className="mt-3 text-xs text-slate-400">参考资料：{report.sources.map((url, index) => <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="mr-3 text-sky-400 hover:underline">AWS 文档 {index + 1} ↗</a>)}</div>}
  </section>;
}

export default function PracticePage() {
  const router = useRouter();
  const [options, setOptions] = useState<TicketOptions | null>(null);
  const [models, setModels] = useState<LlmModels | null>(null);
  const [history, setHistory] = useState<TicketSummary[]>([]);
  const [ticket, setTicket] = useState<TicketSession | null>(null);
  const [serviceId, setServiceId] = useState("");
  const [fromServiceLink, setFromServiceLink] = useState(false);
  const [category, setCategory] = useState("troubleshooting");
  const [personaId, setPersonaId] = useState("novice_pm");
  const [modelId, setModelId] = useState("");
  const [impact, setImpact] = useState("production_degraded");
  const [difficulty, setDifficulty] = useState("intermediate");
  const [crossService, setCrossService] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [operation, setOperation] = useState("");
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollStateRef = useRef<{ ticketId: string; messageCount: number } | null>(null);

  function restoreDraft(active: TicketSession | null) {
    if (!active) return;
    if (active.status === "closed") {
      localStorage.removeItem(draftKey(active.ticket_id));
      setDraft(""); return;
    }
    try {
      const saved = JSON.parse(localStorage.getItem(draftKey(active.ticket_id)) || "{}");
      setDraft(saved.message || saved.finalAnswer || "");
    } catch { setDraft(""); }
  }

  function saveDraft(message: string) {
    if (ticket) localStorage.setItem(draftKey(ticket.ticket_id), JSON.stringify({ message }));
  }

  useEffect(() => {
    if (!ticket) {
      scrollStateRef.current = null;
      return;
    }

    const previous = scrollStateRef.current;
    scrollStateRef.current = { ticketId: ticket.ticket_id, messageCount: ticket.messages.length };
    if (!previous || previous.ticketId !== ticket.ticket_id) {
      window.scrollTo({ top: 0 });
      return;
    }
    if (ticket.messages.length > previous.messageCount) {
      bottomRef.current?.scrollIntoView({ block: "nearest" });
    }
  }, [ticket]);

  useEffect(() => {
    const user = getStoredUser();
    if (!user) { router.replace("/login"); return; }
    let cancelled = false;
    const requestedId = new URLSearchParams(window.location.search).get("ticket");
    const scopedId = localStorage.getItem(activeTicketKey(user.user_id));
    const legacyKey = `sage_active_ticket_${user.user_id}`;
    const legacyId = localStorage.getItem(legacyKey);
    const savedId = requestedId || scopedId || legacyId;
    Promise.all([fetchTicketOptions(), fetchTickets(), fetchLlmModels().catch(() => null),
      savedId ? fetchTicket(savedId).catch(() => null) : Promise.resolve(null)])
      .then(([available, tickets, availableModels, active]) => {
        if (cancelled) return;
        setOptions(available); setHistory(tickets); setModels(availableModels); setTicket(active);
        restoreDraft(active);
        if (active && savedId === legacyId && !scopedId) {
          localStorage.setItem(activeTicketKey(user.user_id), active.ticket_id);
          localStorage.removeItem(legacyKey);
        }
        const requestedService = new URLSearchParams(window.location.search).get("service");
        const validService = available.services.find(item => item.id === requestedService);
        setFromServiceLink(Boolean(validService));
        setServiceId(current => current || validService?.id || available.services[0]?.id || "");
        if (savedId && !active) {
          if (!requestedId || localStorage.getItem(activeTicketKey(user.user_id)) === requestedId)
            localStorage.removeItem(activeTicketKey(user.user_id));
          if (requestedId) window.history.replaceState(null, "", "/practice");
          if (requestedId || scopedId) setError("工单不存在或不属于当前 Profile；请切回对应方向后重试。");
        }
        if (!requestedId && hasPendingTicketJob()) {
          setBusy(true); setOperation("resume");
          resumeTicketJob().then(result => {
            if (!cancelled) { setTicket(result); restoreDraft(result); }
          }).catch(err => { if (!cancelled) setError((err as Error).message); })
            .finally(() => { if (!cancelled) { setBusy(false); setOperation(""); } });
        }
      })
      .catch(err => { if (!cancelled) setError((err as Error).message); });
    return () => { cancelled = true; };
  }, [router]);

  async function begin() {
    const user = getStoredUser();
    if (!user) return;
    setBusy(true); setOperation("create"); setError("");
    try {
      const created = await startTicket({ serviceId, category, personaId, modelId,
        impact, difficulty, crossService });
      localStorage.setItem(activeTicketKey(user.user_id), created.ticket_id);
      window.history.replaceState(null, "", `/practice?ticket=${encodeURIComponent(created.ticket_id)}`);
      setTicket(created); setDraft("");
      setHistory(await fetchTickets());
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); setOperation(""); }
  }

  async function openTicket(id: string) {
    const user = getStoredUser();
    if (!user) return;
    setBusy(true); setError("");
    try {
      const loaded = await fetchTicket(id);
      localStorage.setItem(activeTicketKey(user.user_id), id);
      window.history.replaceState(null, "", `/practice?ticket=${encodeURIComponent(id)}`);
      setTicket(loaded); setDraft("");
      restoreDraft(loaded);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  function backToList() {
    const user = getStoredUser();
    if (user) localStorage.removeItem(activeTicketKey(user.user_id));
    window.history.replaceState(null, "", "/practice");
    setTicket(null); setDraft(""); setError("");
    fetchTickets().then(setHistory).catch(() => {});
  }

  async function send() {
    if (!ticket || draft.trim().length < 2) return;
    setBusy(true); setOperation("send"); setError("");
    try {
      setTicket(await sendTicketMessage(ticket.ticket_id, draft.trim()));
      setDraft("");
      saveDraft("");
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); setOperation(""); }
  }

  async function finish() {
    if (!ticket || draft.trim().length < 30) return;
    setBusy(true); setOperation("report"); setError("");
    try {
      setTicket(await finishTicket(ticket.ticket_id, draft.trim()));
      localStorage.removeItem(draftKey(ticket.ticket_id));
      setDraft("");
      setHistory(await fetchTickets());
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); setOperation(""); }
  }

  const selectedService = options?.services.find(item => item.id === serviceId);
  const selectedCategory = options?.categories.find(item => item.id === category);
  const selectedPersona = options?.personas.find(item => item.id === personaId);

  return <main className={`min-h-screen flex-1 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100 ${ticket ? "px-0 py-0" : "px-6 py-10"}`}>
    <div className={ticket ? "sage-content sage-content--reading mx-auto max-w-5xl" : "sage-content mx-auto max-w-6xl"}>
      {!ticket && <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.2em] text-emerald-400">Ticket simulation lab</p>
          <h1 className="sage-page-title mt-2 text-3xl font-bold">模拟客户工单实战</h1>
          <p className="sage-page-description mt-3 max-w-3xl text-sm leading-7 text-slate-400">选择当前 Profile 下的 AWS 服务、工单类别和客户画像；你需要逐步澄清影响、索取证据并推动问题闭环，最后获得六维复盘报告。</p>
        </div>
        <Link href="/practice/legacy" className="rounded-lg border border-slate-700 px-4 py-2 text-xs text-slate-300 hover:border-emerald-600">查看旧版固定场景 →</Link>
      </div>}

      {error && <div role="alert" className="mb-6 rounded-xl border border-rose-700 bg-rose-950/40 p-4 text-sm text-rose-200">{error}</div>}
      {busy && operation !== "send" && <div role="status" className="mb-5 rounded-xl border border-sky-800 bg-sky-950/30 p-4 text-sm text-sky-200">
        {operation === "report" ? "正在核对对话并生成复盘报告。" : operation === "resume" ? "正在恢复之前的工单任务。" : "正在准备案例并检查证据、技术结论与配置是否一致。"}
        <span className="ml-2 text-slate-400">任务在后台保存，刷新页面可以继续。</span>
      </div>}

      {!ticket ? <>
        <section className="rounded-2xl border border-slate-800 bg-slate-900/80 p-6 md:p-8">
          <p className="text-xs font-semibold text-emerald-400">实战小助手 · 创建工单</p>
          <h2 className="mt-2 text-xl font-semibold">先设置这次技术支持工单</h2>
          <p className="mt-2 text-xs text-slate-500">当前 Profile：{options?.profile_id || "加载中"}</p>
          {fromServiceLink &&
            <p className="mt-3 rounded-lg border border-emerald-800 bg-emerald-950/30 p-3 text-xs text-emerald-200">已从测评报告带入服务。新工单将生成独立案例，原报告的薄弱点仅作为练习方向，不保证生成相同故障。</p>}
          <div className="mt-6 grid gap-4 md:grid-cols-2">
            <label className="text-sm text-slate-300">服务
              <select value={serviceId} onChange={event => setServiceId(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-slate-100">
                {(options?.services || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              <span className="mt-2 block text-xs leading-5 text-slate-500">{selectedService?.summary}</span>
            </label>
            <label className="text-sm text-slate-300">工单类别
              <select value={category} onChange={event => setCategory(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-slate-100">
                {(options?.categories || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              <span className="mt-2 block text-xs leading-5 text-slate-500">{selectedCategory?.description}</span>
            </label>
            <label className="text-sm text-slate-300">客户画像
              <select value={personaId} onChange={event => setPersonaId(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-slate-100">
                {(options?.personas || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
              </select>
              {selectedPersona && <span className="mt-2 block text-xs leading-5 text-slate-500">{selectedPersona.description}<br />
                服务了解 {selectedPersona.expertise}/5 · 耐心 {selectedPersona.patience}/5 · 配合度 {selectedPersona.cooperation}/5</span>}
            </label>
            <label className="text-sm text-slate-300">对话模型
              <select value={modelId} onChange={event => setModelId(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-slate-100">
                <option value="">默认模型{models?.default_model ? ` · ${models.default_model}` : ""}</option>
                {(models?.models || []).map(item => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
          </div>
          <details className="mt-5 rounded-xl border border-slate-700 bg-slate-950/40 p-4">
            <summary className="cursor-pointer text-sm font-semibold text-slate-200">高级设置</summary>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="text-sm text-slate-300">业务影响
                <select value={impact} onChange={event => setImpact(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3">
                  {(options?.impacts || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-300">技术难度
                <select value={difficulty} onChange={event => setDifficulty(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3">
                  {(options?.difficulties || []).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
                </select>
              </label>
            </div>
            <label className="mt-4 flex items-center gap-3 text-sm text-slate-300">
              <input type="checkbox" checked={crossService} onChange={event => setCrossService(event.target.checked)}
                className="h-4 w-4 accent-emerald-500" />
              允许出现跨服务依赖
            </label>
          </details>
          {models && !models.configured && <p className="mt-4 text-sm text-amber-300">模型尚未配置；可先查看旧版固定场景。</p>}
          <button type="button" onClick={begin} disabled={busy || !options || !serviceId || models?.configured === false}
            className="mt-6 rounded-lg bg-emerald-600 px-6 py-3 text-sm font-semibold hover:bg-emerald-500 disabled:opacity-40">{busy ? "创建中…" : "开始模拟工单"}</button>
          <p className="mt-3 text-xs text-slate-500">案例会先检查再开始练习。请根据客户已提供的信息判断；需要操作指引的客户可能暂时无法提供证据。</p>
        </section>
        {history.length > 0 && <section className="mt-8">
          <h2 className="mb-4 text-lg font-semibold">最近工单</h2>
          <div className="grid gap-3 md:grid-cols-2">{history.slice(0, 2).map(item => <button key={item.ticket_id} type="button" disabled={busy} onClick={() => openTicket(item.ticket_id)}
            className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-left text-sm hover:border-emerald-600 disabled:opacity-40">
            <span><span className="font-medium">{item.title}</span><span className="ml-2 text-xs text-slate-500">{item.category_label} · {item.status === "closed" ? "已结案" : "处理中"}</span></span>
            <span className="shrink-0 text-emerald-400">{item.overall_score === null ? "继续 →" : `${item.overall_score} 分 →`}</span>
          </button>)}</div>
          <Link href="/history?tab=tickets" className="mt-4 inline-block text-sm text-emerald-300 hover:underline">查看全部工单 →</Link>
        </section>}
      </> : <section className="flex min-h-[calc(100vh-4rem)] flex-col border-x border-slate-800 bg-slate-950/70">
        <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur md:px-7">
          <div className="flex items-center justify-between gap-4">
            <button type="button" disabled={busy} onClick={backToList} className="shrink-0 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-800 hover:text-white disabled:opacity-50">← 工单列表</button>
            <div className="min-w-0 text-center"><h1 className="truncate text-sm font-semibold md:text-base">{ticket.title}</h1>
              <p className="mt-1 truncate text-[11px] text-slate-500">{ticket.customer_name} · {ticket.category_label} · {ticket.impact_label} · {ticket.status === "closed" ? "已结案" : `${ticket.turn_count}/${ticket.max_turns} 轮`}</p></div>
            <details className="relative shrink-0 text-right"><summary className="cursor-pointer list-none rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-800">工单信息</summary>
              <div className="absolute right-0 mt-2 w-80 rounded-xl border border-slate-700 bg-slate-900 p-4 text-left text-xs leading-6 shadow-2xl">
                <p className="text-slate-200">{ticket.persona_label} · 客户情绪 {ticket.customer_state?.mood || "平稳"}</p>
                <p className="text-slate-500">服务了解 {ticket.persona_traits.expertise}/5 · 耐心 {ticket.persona_traits.patience}/5 · 配合度 {ticket.persona_traits.cooperation}/5</p>
                <p className="mt-2 text-emerald-300">已收集：{ticket.customer_state?.collected_evidence.map(e => e.label).join("、") || "暂无"}</p>
                <p className="text-amber-300">待指引：{ticket.customer_state?.pending_evidence.map(e => e.label).join("、") || "暂无"}</p>
              </div>
            </details>
          </div>
        </header>

        <div aria-live="polite" className="mx-auto w-full max-w-5xl flex-1 space-y-7 px-4 py-8 md:px-6">
          <div className="flex gap-3">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-sm text-emerald-300">S</div>
            <div className="min-w-0 text-sm leading-7 text-slate-300">
              <p className="font-semibold text-slate-100">实战小助手</p>
              <p>案例的业务背景、故障场景、证据、标准排查路径、诊断思路、根因、解决方案和验证方式，已在创建工单前一次生成并冻结。客户对话只能按这份快照提供信息，不会改变案例事实。</p>
              <p className="mt-1 text-xs text-slate-500">快照 {ticket.case_quality.snapshot_sha256?.slice(0, 12) || "历史案例"} · {ticket.model_id} · {ticket.difficulty_label}</p>
              {ticket.case_quality.source_status !== "supported" && <p className="mt-2 text-xs text-amber-300">技术资料支持尚不完整，结案参考答案仍需人工核查。</p>}
            </div>
          </div>

          {ticket.messages.map((item, index) => <div key={index} className={`flex gap-3 ${item.role === "user" ? "justify-end" : "justify-start"}`}>
            {item.role === "customer" && <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-500/15 text-xs text-sky-300">客</div>}
            <div className={`max-w-[88%] text-sm leading-7 md:max-w-[78%] ${item.role === "user" ? "rounded-3xl bg-slate-800 px-5 py-3 text-white" : "min-w-0 text-slate-200"}`}>
              <p className={`mb-1 text-[11px] font-semibold ${item.role === "user" ? "text-emerald-300" : "text-sky-300"}`}>{item.kind === "final_summary" ? "你 · 工单总结" : item.role === "user" ? "你 · 技术支持" : ticket.customer_name}</p>
              <p className="whitespace-pre-wrap">{item.content}</p>
            </div>
          </div>)}

          {busy && operation === "send" && <div className="flex gap-3 text-sm text-slate-400"><div className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-500/15 text-xs text-sky-300">客</div><p className="pt-1">客户正在回复…</p></div>}
          {ticket.report && <div className="flex gap-3"><div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-500/15 text-sm text-emerald-300">S</div><div className="min-w-0 flex-1"><p className="mb-2 text-sm font-semibold">实战小助手 · 复盘报告</p><Report report={ticket.report} /><QualityFeedbackForm recordType="ticket" recordId={ticket.ticket_id} /></div></div>}
          <div ref={bottomRef} />
        </div>

        {ticket.status === "open" ? <div className="sticky bottom-0 z-10 bg-gradient-to-t from-slate-950 via-slate-950 to-transparent px-4 pb-5 pt-8">
          <div className="mx-auto max-w-3xl rounded-3xl border border-slate-700 bg-slate-900 p-3 shadow-2xl focus-within:border-slate-500">
            <label htmlFor="ticket-message" className="sr-only">回复客户或填写工单总结</label>
            <textarea id="ticket-message" value={draft} onChange={event => { setDraft(event.target.value); saveDraft(event.target.value); }} maxLength={4000}
              disabled={busy} rows={3} onKeyDown={event => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && draft.trim().length >= 2 && draft.length <= 1200 && ticket.turn_count < ticket.max_turns) {
                  event.preventDefault(); void send();
                }
              }}
              placeholder={ticket.turn_count < 2 ? "回复客户、澄清影响或索取日志…" : "继续和客户沟通，或在这里写完整总结后提交复盘…"}
              className="w-full resize-none bg-transparent px-2 py-1 text-sm leading-6 outline-none placeholder:text-slate-600 disabled:opacity-50" />
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-3">
              <p className="px-2 text-[11px] text-slate-500">Enter 发送 · Shift+Enter 换行 · 总结也使用这个输入框</p>
              <div className="flex gap-2">
                <button type="button" onClick={finish} disabled={busy || ticket.turn_count < 2 || draft.trim().length < 30}
                  className="rounded-full border border-sky-700 px-4 py-2 text-xs font-semibold text-sky-300 hover:bg-sky-950 disabled:opacity-35">{operation === "report" ? "生成复盘…" : "提交总结"}</button>
                <button type="button" onClick={send} disabled={busy || draft.trim().length < 2 || draft.length > 1200 || ticket.turn_count >= ticket.max_turns}
                  className="rounded-full bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-35">{operation === "send" ? "回复中…" : "发送 ↑"}</button>
              </div>
            </div>
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-600">至少交流两轮后可提交总结；报告只评价本次模拟对话，不代表 AWS 专家认证。</p>
        </div> : <div className="sticky bottom-0 flex flex-wrap justify-center gap-3 border-t border-slate-800 bg-slate-950/95 p-4 text-center"><Link href={`/practice/contribute?ticket=${encodeURIComponent(ticket.ticket_id)}`} className="rounded-full border border-emerald-700 px-5 py-2 text-sm text-emerald-300 hover:bg-emerald-950">提交教学案例建议</Link><button type="button" onClick={backToList} className="rounded-full border border-slate-700 px-5 py-2 text-sm text-slate-300 hover:bg-slate-800">返回工单列表</button></div>}
      </section>}
    </div>
  </main>;
}

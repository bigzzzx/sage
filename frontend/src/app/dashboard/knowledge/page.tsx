"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import { actOnKnowledgeEntry, fetchKnowledgeCoverage, fetchKnowledgeEntries, fetchTaxonomy, reindexKnowledge,
  saveKnowledgeEntry, type FullTaxonomy, type KnowledgeCoverage, type KnowledgeEntry, type KnowledgeInput } from "@/lib/api";

const FIELDS = [
  ["symptom", "客户现象"], ["investigation", "排查过程"], ["root_cause", "问题根因"],
  ["resolution", "解决方案"], ["verification", "验证方式"],
] as const;
const blankDetails = () => Object.fromEntries(FIELDS.map(([key]) => [key, ""])) as Record<string, string>;
const statusName: Record<string, string> = { draft: "草稿", submitted: "待审核", published: "已发布", archived: "已下架" };
const errorText = (value: unknown) => value instanceof Error ? value.message : "操作失败";

export default function KnowledgeManagementPage() {
  const router = useRouter();
  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [profile, setProfile] = useState("");
  const [entries, setEntries] = useState<KnowledgeEntry[]>([]);
  const [coverage, setCoverage] = useState<KnowledgeCoverage | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [editingId, setEditingId] = useState("");
  const [replacesId, setReplacesId] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [capabilityId, setCapabilityId] = useState("");
  const [sourceType, setSourceType] = useState<"case" | "official_doc">("case");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [details, setDetails] = useState<Record<string, string>>(blankDetails);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const track = taxonomy?.tracks.find(item => item.id === profile);
  const effectiveServiceId = track?.services.some(item => item.id === serviceId)
    ? serviceId : track?.services[0]?.id || "";
  const service = track?.services.find(item => item.id === effectiveServiceId);
  const selected = entries.find(item => item.id === selectedId);

  useEffect(() => {
    const user = getStoredUser();
    if (!user) { router.replace("/admin/login"); return; }
    if (user.role !== "manager") { router.replace("/"); return; }
    queueMicrotask(() => setProfile(user.current_profile || "big_data"));
    fetchTaxonomy().then(setTaxonomy).catch(reason => setError(errorText(reason)));
  }, [router]);

  const refresh = useCallback(async () => {
    if (!profile) return;
    try { const [rows, report] = await Promise.all([fetchKnowledgeEntries(profile), fetchKnowledgeCoverage()]); setEntries(rows); setCoverage(report); }
    catch (reason) { setError(errorText(reason)); }
  }, [profile]);
  useEffect(() => {
    if (!profile) return;
    Promise.all([fetchKnowledgeEntries(profile), fetchKnowledgeCoverage()]).then(([rows, report]) => { setEntries(rows); setCoverage(report); }).catch(reason => setError(errorText(reason)));
  }, [profile]);
  function resetForm() { setEditingId(""); setReplacesId(""); setTitle(""); setUrl(""); setDetails(blankDetails()); setCapabilityId(""); }
  function edit(item: KnowledgeEntry) {
    setProfile(item.profile_id); setServiceId(item.service_id); setCapabilityId(item.capability_id);
    setSourceType(item.source_type); setTitle(item.title); setUrl(item.url);
    setDetails({ ...blankDetails(), ...item.details }); setEditingId(item.id);
    setReplacesId(item.replaces_entry_id || "");
    setSelectedId(item.id); window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function newVersion(item: KnowledgeEntry) {
    setEditingId(""); setReplacesId(item.id); setProfile(item.profile_id);
    setServiceId(item.service_id); setCapabilityId(item.capability_id);
    setSourceType(item.source_type); setTitle(item.title); setUrl(item.url);
    setDetails(item.source_type === "case" ? { ...blankDetails(), ...item.details } : blankDetails());
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setError(""); setNotice(""); setBusy("save");
    try {
      const input: KnowledgeInput = { profile_id: profile, service_id: effectiveServiceId, capability_id: capabilityId,
        source_type: sourceType, title: title.trim(), url: url.trim(), details: sourceType === "case" ? details : {},
        replaces_entry_id: replacesId || null };
      const saved = await saveKnowledgeEntry(input, editingId || undefined);
      await refresh(); setSelectedId(saved.id); resetForm();
      setNotice("草稿已保存。请预览并确认后再发布；官方文档须先抓取正文。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(""); }
  }
  async function act(item: KnowledgeEntry, action: "capture" | "publish" | "archive") {
    if (action === "archive" && !window.confirm(`确认下架「${item.title}」？下架后将退出检索。`)) return;
    setError(""); setNotice(""); setBusy(`${action}:${item.id}`);
    try {
      const updated = await actOnKnowledgeEntry(item.id, action);
      await refresh(); setSelectedId(updated.id);
      setNotice(action === "capture" ? "已抓取官方正文，请预览内容后发布。"
        : action === "archive" ? "已下架；新检索不会再返回该条目。"
        : updated.index_status === "indexed" ? "发布成功，向量索引已更新。"
          : "已发布，关键词检索可用；向量索引待重建，请检查模型隧道。");
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(""); }
  }

  return <main className="min-h-screen bg-slate-950 px-5 py-10 text-slate-100"><div className="mx-auto max-w-6xl space-y-7">
    <header><p className="text-xs font-semibold tracking-[.2em] text-emerald-400">ADMIN · KNOWLEDGE</p>
      <h1 className="mt-2 text-3xl font-bold">知识库管理</h1>
      <p className="mt-2 text-sm text-slate-400">草稿与投稿不会进入检索。案例仅作教学素材；技术事实须由已核验的 AWS 官方正文支持。</p></header>
    {error && <p role="alert" className="rounded-lg border border-rose-800 bg-rose-950/30 p-3 text-sm text-rose-300">{error}</p>}
    {notice && <p role="status" className="rounded-lg border border-emerald-800 bg-emerald-950/30 p-3 text-sm text-emerald-300">{notice}</p>}
    {coverage && <section className="rounded-xl border border-slate-800 bg-slate-900 p-5 text-sm"><h2 className="font-semibold">知识覆盖</h2>
      <p className="mt-2 text-slate-300">全库 {coverage.chunk_count} 段 · {coverage.services_with_chunks}/{coverage.service_count} 个服务有可检索片段。片段数不等于事实已核验。</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{coverage.services.filter(item => item.profile_id === profile).map(item => <div key={item.service_id} className="rounded-lg bg-slate-950 p-3 text-xs"><span className="font-medium">{item.service_id}</span><span className="ml-2 text-slate-400">{item.chunks} 段 · 官方正文 {item.official_excerpts}/{item.official_refs}</span></div>)}</div>
    </section>}
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{editingId ? "编辑待审核条目" : "新增知识草稿"}</h2>
        <p className="mt-1 text-xs text-slate-400">发布可能需要半分钟。请先移除账号、邮箱、密钥和客户标识。</p></div>
        {(editingId || replacesId) && <button type="button" onClick={resetForm} className="text-sm text-sky-300">取消编辑</button>}</div>
      {replacesId && <p className="mt-3 rounded-lg border border-amber-800 bg-amber-950/20 p-3 text-xs text-amber-200">正在创建替换版本：{replacesId}。新版本审核发布后，旧版会自动下架；草稿阶段旧版仍可检索。</p>}
      <form onSubmit={save} className="mt-5 space-y-4">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="text-sm">Profile<select value={profile} onChange={e => { setProfile(e.target.value); setServiceId(""); setCapabilityId(""); }} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5">{taxonomy?.tracks.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="text-sm">服务<select value={effectiveServiceId} onChange={e => { setServiceId(e.target.value); setCapabilityId(""); }} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5">{track?.services.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="text-sm">能力点<select value={capabilityId} onChange={e => setCapabilityId(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5"><option value="">不限能力点</option>{service?.capabilities?.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label className="text-sm">类型<select value={sourceType} onChange={e => setSourceType(e.target.value as "case" | "official_doc")} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5"><option value="case">教学案例</option><option value="official_doc">AWS 官方文档</option></select></label>
        </div>
        <label className="block text-sm">标题<input required minLength={4} maxLength={160} value={title} onChange={e => setTitle(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5" /></label>
        <label className="block text-sm">{sourceType === "case" ? "AWS 官方参考链接（可选）" : "AWS 官方文档链接（必填）"}<input type="url" required={sourceType === "official_doc"} value={url} onChange={e => setUrl(e.target.value)} placeholder="https://docs.amazonaws.cn/glue/latest/dg/..." className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5" /></label>
        {sourceType === "case" && <div className="grid gap-3 md:grid-cols-2">{FIELDS.map(([key, label]) => <label key={key} className="text-sm">{label}<textarea value={details[key] || ""} maxLength={4000} rows={3} onChange={e => setDetails({ ...details, [key]: e.target.value })} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-2.5" /></label>)}</div>}
        <button type="submit" disabled={!!busy || !effectiveServiceId} className="rounded-lg bg-emerald-700 px-5 py-2.5 text-sm font-semibold hover:bg-emerald-600 disabled:opacity-50">{busy === "save" ? "保存中…" : "保存草稿"}</button>
      </form>
    </section>
    <section className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">{track?.name || profile} · 知识条目（最近 100 条）</h2>
        <button type="button" disabled={!!busy} onClick={async () => { setBusy("reindex"); setError(""); try { const result = await reindexKnowledge(); setNotice(result.index_status === "indexed" ? "索引已重建" : "向量索引待处理，请检查模型连接"); await refresh(); } catch (reason) { setError(errorText(reason)); } finally { setBusy(""); } }} className="text-sm text-sky-300 disabled:opacity-50">重建向量索引</button></div>
      {entries.length === 0 ? <p className="mt-5 text-sm text-slate-500">暂无草稿或已发布条目。</p> : <div className="mt-4 space-y-3">{entries.map(item => <div key={item.id} className="rounded-xl border border-slate-700 bg-slate-950 p-4">
        <div className="flex flex-wrap items-start justify-between gap-2"><button type="button" onClick={() => setSelectedId(selectedId === item.id ? "" : item.id)} className="text-left font-semibold hover:text-sky-300">{item.title} <span className="ml-2 text-xs text-slate-400">{item.service_id} · {item.source_type === "case" ? "案例" : "官方文档"} · {statusName[item.status]} · {item.chunk_count} 段</span></button>
          <div className="flex flex-wrap gap-3 text-xs">{["draft", "submitted"].includes(item.status) && <>
            <button type="button" disabled={!!busy} onClick={() => edit(item)} className="text-sky-300">编辑</button>
            {item.source_type === "official_doc" && <button type="button" disabled={!!busy} onClick={() => void act(item, "capture")} className="text-sky-300">抓取正文</button>}
            <button type="button" disabled={!!busy} onClick={() => void act(item, "publish")} className="text-emerald-300">审核发布</button></>}
            {item.status === "published" && <button type="button" disabled={!!busy} onClick={() => newVersion(item)} className="text-sky-300">创建新版本</button>}
            {item.status !== "archived" && <button type="button" disabled={!!busy} onClick={() => void act(item, "archive")} className="text-rose-300">下架</button>}</div></div>
        {item.replaces_entry_id && <p className="mt-1 text-xs text-amber-300">替换旧版：{item.replaces_entry_id}</p>}
        <p className="mt-2 text-xs text-slate-500">{item.status === "archived" ? "检索状态：已退出检索" : `向量索引：${item.index_status === "indexed" ? "已更新" : item.index_status === "pending" ? "待更新（关键词可用）" : "未入库"}`} · 创建人 {item.created_by}{item.source_ticket_id ? ` · 来自模拟工单 ${item.source_ticket_id}` : ""}</p>
        {selected?.id === item.id && <div className="mt-4 border-t border-slate-800 pt-4"><p className="mb-2 text-xs text-slate-400">{item.status === "draft" || item.status === "submitted" ? "发布前预览" : "正文预览"} · {item.status === "archived" ? "已下架内容不参与检索" : "仅正文内容进入检索"}</p><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 p-4 text-sm leading-6 text-slate-200">{item.content || "尚无正文。官方文档需先抓取，案例需填写内容。"}</pre>{item.url && <a href={item.url} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs text-sky-300">打开参考链接 ↗</a>}</div>}
      </div>)}</div>}
    </section>
  </div></main>;
}

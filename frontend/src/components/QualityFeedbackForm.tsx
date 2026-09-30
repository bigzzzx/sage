"use client";

import { useState } from "react";
import { submitQualityFeedback } from "@/lib/api";

export default function QualityFeedbackForm({ recordType, recordId, questionId }: {
  recordType: "assessment" | "ticket"; recordId: string; questionId?: string;
}) {
  const [category, setCategory] = useState("score");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  return <details className="mt-5 rounded-xl border border-slate-700 bg-slate-900/70 p-4 text-sm">
    <summary className="cursor-pointer text-sky-300">发现题目、评分或参考资料有问题？提交纠错</summary>
    <div className="mt-4 space-y-3">
      <p className="text-xs text-slate-400">反馈将绑定这条{recordType === "ticket" ? "工单" : questionId ? "题目" : "测评"}的原始内容，管理员复核前不会自动改变成绩。</p>
      <label className="block text-slate-300">问题类型
        <select value={category} onChange={event => setCategory(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-950 p-2">
          <option value="score">评分不合理</option><option value="question">题目或案例有误</option>
          <option value="answer">参考答案有误</option><option value="citation">引用不支持结论</option>
          <option value="document">文档失效或语言不符</option><option value="other">其他</option>
        </select>
      </label>
      <label className="block text-slate-300">具体问题和建议
        <textarea value={description} onChange={event => setDescription(event.target.value)} maxLength={2000} rows={3}
          className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 p-3" placeholder="请指出哪里有误，并提供你认为正确的依据或文档链接。" />
      </label>
      <button type="button" disabled={busy || description.trim().length < 10} onClick={async () => {
        setBusy(true); setStatus("");
        try {
          await submitQualityFeedback({ record_type: recordType, record_id: recordId,
            question_id: questionId, category, description: description.trim() });
          setDescription(""); setStatus("已提交，等待管理员复核。原记录保持不变。");
        } catch (error) { setStatus(String(error)); } finally { setBusy(false); }
      }} className="rounded-lg bg-sky-700 px-4 py-2 text-white disabled:opacity-40">{busy ? "提交中…" : "提交纠错"}</button>
      {status && <p role="status" className="text-xs text-sky-300">{status}</p>}
    </div>
  </details>;
}

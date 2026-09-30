"use client";

import { useEffect, useState } from "react";
import { fetchQualityFeedback, type QualityFeedback } from "@/lib/api";

export default function MyQualityFeedback() {
  const [items, setItems] = useState<QualityFeedback[]>([]);
  useEffect(() => { fetchQualityFeedback().then(setItems).catch(() => {}); }, []);
  if (!items.length) return null;
  return <section className="rounded-xl border border-slate-800 bg-slate-900 p-5">
    <h2 className="text-lg font-semibold">我的纠错反馈</h2>
    <div className="mt-3 space-y-2">{items.slice(0, 5).map(item => <div key={item.id} className="rounded-lg bg-slate-950 p-3 text-sm">
      <div className="flex justify-between gap-2"><span>{item.record_type === "assessment" ? "测评" : "工单"} · {item.category}</span><span className="text-emerald-300">{item.status === "open" ? "待复核" : item.status === "accepted" ? "已采纳" : item.status === "needs_info" ? "需补充" : "未采纳"}</span></div>
      <p className="mt-1 line-clamp-2 text-xs text-slate-400">{item.description}</p>{item.review_note && <p className="mt-2 text-xs text-amber-300">复核意见：{item.review_note}</p>}
    </div>)}</div>
  </section>;
}

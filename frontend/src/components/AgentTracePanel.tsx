"use client";

import { useState } from "react";
import type { AgentStep } from "@/lib/api";

const AGENT_LABEL: Record<string, { name: string; color: string; icon: string }> = {
  orchestrator: { name: "编排器", color: "text-slate-300", icon: "🧭" },
  diagnosis: { name: "诊断 Agent", color: "text-amber-300", icon: "🩺" },
  planning: { name: "规划 Agent", color: "text-emerald-300", icon: "📋" },
  reflection: { name: "反思 Agent", color: "text-sky-300", icon: "🪞" },
  scoring: { name: "评分 Agent", color: "text-purple-300", icon: "📊" },
};

export default function AgentTracePanel({ trace }: { trace: AgentStep[] }) {
  const [open, setOpen] = useState(false);
  if (!trace || trace.length === 0) return null;

  const totalMs = trace.reduce((a, s) => a + (s.elapsed_ms || 0), 0);

  return (
    <section className="bg-slate-800 rounded-xl border border-slate-700">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full p-4 flex items-center justify-between hover:bg-slate-800/60 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span>🤖</span>
          <span className="font-semibold">AI 工作流记录</span>
          <span className="text-xs text-slate-500">
            （自研固定流程 · {trace.length} 步 · 已记录步骤耗时 {(totalMs / 1000).toFixed(1)}s）
          </span>
        </div>
        <span className="text-slate-500 text-sm">{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-slate-700">
          <div className="relative pl-6 mt-3">
            {/* 时间线竖线 */}
            <div className="absolute left-2 top-0 bottom-0 w-px bg-slate-700" />
            {trace.map((s, i) => {
              const meta = AGENT_LABEL[s.agent] || {
                name: s.agent,
                color: "text-slate-300",
                icon: "•",
              };
              const statusColor =
                s.status === "failed"
                  ? "text-rose-400"
                  : s.status === "skipped"
                    ? "text-slate-500"
                    : "text-emerald-400";
              return (
                <div key={i} className="relative mb-3 last:mb-0">
                  {/* 时间线圆点 */}
                  <div className="absolute -left-[18px] top-1.5 w-3 h-3 rounded-full bg-slate-900 border-2 border-slate-600" />
                  <div className="bg-slate-900/40 rounded p-3 border border-slate-800">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className={`font-medium text-sm ${meta.color}`}>
                        {meta.icon} {meta.name}
                      </span>
                      {s.label && (
                        <span className="text-xs text-slate-300">{s.label}</span>
                      )}
                      <span className={`text-[10px] ${statusColor}`}>
                        {s.status === "failed"
                          ? "失败"
                          : s.status === "skipped"
                            ? "跳过"
                            : "✓"}
                      </span>
                      {!!s.elapsed_ms && (
                        <span className="text-[10px] text-slate-500 ml-auto">
                          {s.elapsed_ms} ms
                        </span>
                      )}
                    </div>
                    {s.input_summary && (
                      <div className="text-xs text-slate-400">
                        <span className="text-slate-500">输入：</span>
                        {s.input_summary}
                      </div>
                    )}
                    {s.output_summary && (
                      <div className="text-xs text-slate-300 mt-0.5">
                        <span className="text-slate-500">产出：</span>
                        {s.output_summary}
                      </div>
                    )}
                    {s.error && (
                      <div className="text-xs text-rose-400 mt-0.5 break-all">
                        错误：{s.error}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

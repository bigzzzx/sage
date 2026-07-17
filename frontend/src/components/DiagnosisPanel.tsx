"use client";

import type { KnowledgeGap } from "@/lib/api";

const SEVERITY_STYLE: Record<
  string,
  { color: string; label: string; ring: string }
> = {
  critical: {
    color: "bg-rose-600/20 text-rose-300 border-rose-700",
    label: "🔴 严重",
    ring: "ring-rose-500/30",
  },
  major: {
    color: "bg-amber-600/20 text-amber-300 border-amber-700",
    label: "🟠 重要",
    ring: "ring-amber-500/30",
  },
  minor: {
    color: "bg-slate-600/30 text-slate-300 border-slate-700",
    label: "🟡 轻微",
    ring: "ring-slate-500/30",
  },
};

export default function DiagnosisPanel({ gaps }: { gaps: KnowledgeGap[] }) {
  if (!gaps || gaps.length === 0) {
    return null;
  }

  // 按 severity 分组排序
  const order = { critical: 0, major: 1, minor: 2 } as const;
  const sorted = [...gaps].sort(
    (a, b) =>
      (order[a.severity as keyof typeof order] ?? 3) -
      (order[b.severity as keyof typeof order] ?? 3),
  );

  const counts = sorted.reduce<Record<string, number>>((acc, g) => {
    acc[g.severity] = (acc[g.severity] || 0) + 1;
    return acc;
  }, {});

  return (
    <section className="bg-slate-800 rounded-xl p-6 border border-emerald-700/40">
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          🩺 知识盲区诊断
          <span className="text-xs text-slate-400 font-normal">
            （Diagnosis Agent · 像资深 SE 一样 review 了你的回答）
          </span>
        </h2>
        <div className="flex gap-2 text-xs">
          {counts.critical && (
            <span className="px-2 py-0.5 rounded bg-rose-600/20 text-rose-300">
              严重 {counts.critical}
            </span>
          )}
          {counts.major && (
            <span className="px-2 py-0.5 rounded bg-amber-600/20 text-amber-300">
              重要 {counts.major}
            </span>
          )}
          {counts.minor && (
            <span className="px-2 py-0.5 rounded bg-slate-600/30 text-slate-300">
              轻微 {counts.minor}
            </span>
          )}
        </div>
      </div>
      <p className="text-xs text-slate-500 mb-4">
        下列盲区会精准对应到学习计划的每一天任务
      </p>

      <div className="space-y-3">
        {sorted.map((g) => {
          const style = SEVERITY_STYLE[g.severity] || SEVERITY_STYLE.minor;
          return (
            <div
              key={g.gap_id}
              className={`bg-slate-900/40 rounded-lg p-4 border ${style.color}`}
            >
              <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded ${style.color}`}
                  >
                    {style.label}
                  </span>
                  <span className="font-semibold text-slate-100">{g.title}</span>
                  {g.capability_name && (
                    <span className="text-[10px] text-slate-500 px-1.5 py-0.5 rounded bg-slate-800">
                      {g.capability_name}
                    </span>
                  )}
                </div>
                <span className="text-[10px] text-slate-500 font-mono">
                  {g.gap_id}
                </span>
              </div>

              {g.evidence_quote && g.evidence_quote !== "未提及" && (
                <div className="mb-2 text-xs text-slate-400 italic border-l-2 border-slate-700 pl-2">
                  你的原话："{g.evidence_quote}"
                </div>
              )}

              {g.misunderstanding && (
                <div className="mb-2">
                  <span className="text-[11px] text-rose-400 mr-1">
                    ❌ 你的理解：
                  </span>
                  <span className="text-sm text-slate-200">
                    {g.misunderstanding}
                  </span>
                </div>
              )}

              {g.correct_understanding && (
                <div className="mb-2">
                  <span className="text-[11px] text-emerald-400 mr-1">
                    ✅ 正确理解：
                  </span>
                  <span className="text-sm text-slate-200">
                    {g.correct_understanding}
                  </span>
                </div>
              )}

              {g.suggested_doc_urls && g.suggested_doc_urls.length > 0 && (
                <div className="mt-2 space-y-1">
                  {g.suggested_doc_urls.map((u, i) => (
                    <a
                      key={i}
                      href={u}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-sky-400 hover:underline inline-flex items-center gap-1 break-all mr-3"
                    >
                      <span>🔗</span>
                      <span>对症文档</span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

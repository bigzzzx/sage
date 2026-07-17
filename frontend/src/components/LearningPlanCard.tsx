"use client";

import type { KnowledgeGap, LearningPlan, LearningTask } from "@/lib/api";

const TASK_TYPE_STYLE: Record<string, { label: string; color: string }> = {
  reading: { label: "📖 阅读", color: "bg-sky-600/30 text-sky-300" },
  video: { label: "🎥 视频", color: "bg-purple-600/30 text-purple-300" },
  lab: { label: "🧪 实验", color: "bg-emerald-600/30 text-emerald-300" },
  review: { label: "🔍 复盘", color: "bg-amber-600/30 text-amber-300" },
  quiz: { label: "📝 自测", color: "bg-rose-600/30 text-rose-300" },
};

function TaskBlock({
  task,
  gapMap,
}: {
  task: LearningTask;
  gapMap: Map<string, KnowledgeGap>;
}) {
  const style = TASK_TYPE_STYLE[task.task_type] || {
    label: task.task_type,
    color: "bg-slate-600/30 text-slate-300",
  };

  const hasConcepts = task.concepts && task.concepts.length > 0;
  const hasHandsOn = !!(task.hands_on && task.hands_on.trim());
  const hasTroubleshoot = !!(task.troubleshooting && task.troubleshooting.trim());
  const hasLegacyResources =
    !hasConcepts && task.resources && task.resources.length > 0;
  const hasLegacyDesc =
    !hasHandsOn && !hasTroubleshoot && !!(task.description && task.description.trim());

  const targetedGaps = (task.targets_gap_ids || [])
    .map((id) => gapMap.get(id))
    .filter((g): g is KnowledgeGap => Boolean(g));

  return (
    <div className="bg-slate-950/40 rounded-lg p-4 border border-slate-800">
      {/* 头部 */}
      <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-emerald-400 font-bold">{task.day}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${style.color}`}>
            {style.label}
          </span>
          <span className="text-slate-100 font-medium">{task.topic}</span>
        </div>
      </div>

      {/* 学习目标 */}
      {task.objective && (
        <div className="mb-3 px-3 py-2 bg-emerald-900/20 border-l-2 border-emerald-500 rounded">
          <span className="text-[10px] text-emerald-400 mr-1">🎯 学习目标</span>
          <span className="text-sm text-slate-200">{task.objective}</span>
        </div>
      )}

      {/* 针对盲区（agent 化的关键 UI） */}
      {targetedGaps.length > 0 && (
        <div className="mb-3 px-3 py-2 bg-rose-900/15 border-l-2 border-rose-500/60 rounded">
          <div className="text-[10px] text-rose-300 mb-1">
            🩺 直击盲区
          </div>
          <div className="flex flex-wrap gap-1.5">
            {targetedGaps.map((g) => (
              <span
                key={g.gap_id}
                className="text-xs px-2 py-0.5 rounded bg-slate-900/60 border border-rose-700/40 text-slate-200"
                title={g.misunderstanding}
              >
                {g.title}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 预期产出物 */}
      {task.deliverable && (
        <div className="mb-3 px-3 py-2 bg-sky-900/15 border-l-2 border-sky-500/60 rounded">
          <span className="text-[10px] text-sky-300 mr-1">📦 预期产出</span>
          <span className="text-sm text-slate-200">{task.deliverable}</span>
        </div>
      )}

      {/* 核心概念 + 文档链接 */}
      {hasConcepts && (
        <div className="mb-3">
          <div className="text-xs text-slate-400 mb-1.5 flex items-center gap-1">
            <span>📘</span>
            <span>核心概念与原理</span>
          </div>
          <ul className="space-y-1.5">
            {task.concepts!.map((c, i) => (
              <li
                key={i}
                className="text-sm bg-slate-900/40 rounded px-3 py-2 border border-slate-800"
              >
                <div className="text-slate-200 leading-relaxed mb-1">
                  {c.point}
                </div>
                {c.url ? (
                  <a
                    href={c.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-sky-400 hover:underline inline-flex items-center gap-1 break-all"
                  >
                    <span>🔗</span>
                    <span>AWS 中国区官方文档</span>
                  </a>
                ) : (
                  <span className="text-xs text-slate-500">📄 暂无对应文档</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 实操副证 */}
      {hasHandsOn && (
        <div className="mb-3">
          <div className="text-xs text-slate-400 mb-1.5 flex items-center gap-1">
            <span>🧪</span>
            <span>实操副证（动手验证）</span>
          </div>
          <pre className="text-sm text-slate-200 bg-slate-900/40 rounded px-3 py-2 border border-slate-800 whitespace-pre-wrap font-sans leading-relaxed">
            {task.hands_on}
          </pre>
        </div>
      )}

      {/* 故障排查练习 */}
      {hasTroubleshoot && (
        <div className="mb-1">
          <div className="text-xs text-slate-400 mb-1.5 flex items-center gap-1">
            <span>🔧</span>
            <span>故障排查练习</span>
          </div>
          <pre className="text-sm text-slate-200 bg-amber-950/20 border-l-2 border-amber-500 rounded px-3 py-2 whitespace-pre-wrap font-sans leading-relaxed">
            {task.troubleshooting}
          </pre>
        </div>
      )}

      {/* 兼容旧版数据：无新字段时显示 description + resources */}
      {hasLegacyDesc && (
        <p className="text-sm text-slate-300 leading-relaxed mb-2">
          {task.description}
        </p>
      )}
      {hasLegacyResources && (
        <ul className="space-y-1">
          {task.resources!.map((r, ri) => (
            <li key={ri} className="text-xs">
              {r.url ? (
                <a
                  href={r.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-400 hover:underline break-all"
                >
                  🔗 {r.title}
                </a>
              ) : (
                <span className="text-slate-400">📄 {r.title}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function LearningPlanCard({
  plan,
  gaps,
}: {
  plan: LearningPlan;
  gaps?: KnowledgeGap[];
}) {
  const gapMap = new Map<string, KnowledgeGap>();
  (gaps || []).forEach((g) => gapMap.set(g.gap_id, g));
  return (
    <div>
      <p className="text-emerald-400 font-medium mb-1">{plan.plan_name}</p>
      {plan.overall_assessment && (
        <p className="text-slate-300 mb-4 leading-relaxed">
          {plan.overall_assessment}
        </p>
      )}

      {plan.priority_dimensions && plan.priority_dimensions.length > 0 && (
        <div className="mb-5">
          <span className="text-slate-400 text-sm mr-2">优先提升：</span>
          {plan.priority_dimensions.map((d) => (
            <span
              key={d}
              className="inline-block bg-emerald-600/30 border border-emerald-600 text-emerald-300 text-xs px-2 py-0.5 rounded mr-2"
            >
              {d}
            </span>
          ))}
        </div>
      )}

      <div className="space-y-5">
        {plan.weekly_plan.map((w) => {
          return (
            <div
              key={w.week}
              className="bg-slate-900/50 rounded-lg p-4 border border-slate-700"
            >
              <div className="flex items-center gap-3 mb-4 flex-wrap">
                <span className="bg-emerald-600 text-white text-xs px-2 py-1 rounded font-bold">
                  本周
                </span>
                <span className="text-slate-200 font-medium flex-1">
                  {w.focus}
                </span>
                <span className="text-xs text-slate-500">
                  共 {w.tasks.length} 天
                </span>
              </div>
              <div className="space-y-3">
                {w.tasks.map((t, i) => (
                  <TaskBlock key={i} task={t} gapMap={gapMap} />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {plan.verification && (
        <div className="mt-5 p-3 bg-slate-900/50 border-l-4 border-amber-500 rounded">
          <p className="text-xs text-slate-400 mb-1">📌 阶段验证方式</p>
          <p className="text-sm text-slate-200">{plan.verification}</p>
        </div>
      )}
    </div>
  );
}

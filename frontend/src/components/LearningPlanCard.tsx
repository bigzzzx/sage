"use client";

import { useEffect, useState } from "react";
import { fetchLearningProgress, saveLearningProgress, type KnowledgeGap, type LearningPlan, type LearningTask, type TaskProgress } from "@/lib/api";

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
  progress,
  onSave,
}: {
  task: LearningTask;
  gapMap: Map<string, KnowledgeGap>;
  progress?: TaskProgress;
  onSave?: (evidence: string, status: "in_progress" | "blocked" | "submitted") => Promise<void>;
}) {
  const [evidence, setEvidence] = useState(progress?.evidence || "");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  useEffect(() => { if (progress) queueMicrotask(() => setEvidence(progress.evidence)); }, [progress]);
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
                    <span>AWS 官方文档</span>
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
      {(task.preconditions || task.verification_steps || task.risk_and_cleanup) && (
        <div className="mb-3 grid gap-2 text-sm">
          {task.preconditions && <div className="rounded border border-slate-700 bg-slate-900/40 px-3 py-2 text-slate-200"><span className="text-sky-300">前置条件：</span>{task.preconditions}</div>}
          {task.verification_steps && <div className="rounded border border-slate-700 bg-slate-900/40 px-3 py-2 text-slate-200"><span className="text-emerald-300">验收方式：</span>{task.verification_steps}</div>}
          {task.risk_and_cleanup && <div className="rounded border border-amber-700/40 bg-amber-950/20 px-3 py-2 text-slate-200"><span className="text-amber-300">风险与清理：</span>{task.risk_and_cleanup}</div>}
        </div>
      )}
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
      {onSave && <div className="mt-4 border-t border-slate-800 pt-4">
        <label className="mb-2 block text-xs font-semibold text-emerald-300">任务状态：{progress?.status === "verified" ? "已验收" : progress?.status === "submitted" ? "待验收" : progress?.status === "blocked" ? "受阻" : progress?.status === "in_progress" ? "学习中" : "未开始"}</label>
        <textarea value={evidence} onChange={event => setEvidence(event.target.value)} placeholder="记录实验结果、复盘结论或产出物链接（至少 10 字）" className="min-h-20 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-xs text-slate-100 outline-none focus:border-emerald-500" />
        {progress?.review_note && <p className="mb-2 text-xs text-amber-300">验收意见：{progress.review_note}</p>}
        {saveError && <p className="mt-1 text-xs text-rose-400">{saveError}</p>}
        <div className="mt-2 flex flex-wrap gap-2">{(["in_progress", "blocked", "submitted"] as const).map(status => <button key={status}
          disabled={saving || (status !== "in_progress" && evidence.trim().length < 10)} onClick={async () => {
          setSaving(true); setSaveError("");
          try { await onSave(evidence.trim(), status); } catch (error) { setSaveError((error as Error).message); }
          finally { setSaving(false); }
        }} className="rounded-lg bg-emerald-700 px-3 py-1.5 text-xs text-white hover:bg-emerald-600 disabled:opacity-40">{status === "in_progress" ? "标记学习中" : status === "blocked" ? "记录受阻" : "提交证据待验收"}</button>)}</div>
      </div>}
    </div>
  );
}

export default function LearningPlanCard({
  plan,
  gaps,
  assessmentId,
  showOverallAssessment = true,
}: {
  plan: LearningPlan;
  gaps?: KnowledgeGap[];
  assessmentId?: string;
  showOverallAssessment?: boolean;
}) {
  const [progress, setProgress] = useState<TaskProgress[]>([]);
  useEffect(() => {
    if (!assessmentId) return;
    let cancelled = false;
    fetchLearningProgress(assessmentId).then(items => { if (!cancelled) setProgress(items); }).catch(() => {});
    return () => { cancelled = true; };
  }, [assessmentId]);
  const total = plan.weekly_plan.reduce((sum, week) => sum + week.tasks.length, 0);
  const gapMap = new Map<string, KnowledgeGap>();
  (gaps || []).forEach((g) => gapMap.set(g.gap_id, g));
  return (
    <div>
      <p className="text-emerald-400 font-medium mb-1">{plan.plan_name}</p>
      {assessmentId && <p className="mb-3 text-xs text-slate-400">已提交证据：{progress.filter(item => ["submitted", "verified"].includes(item.status)).length} / {total} 项 · 管理员已验收 {progress.filter(item => item.status === "verified").length} 项</p>}
      {showOverallAssessment && plan.overall_assessment && (
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
        {plan.weekly_plan.map((w, weekIndex) => {
          return (
            <details
              key={w.week}
              className="bg-slate-900/50 rounded-lg p-4 border border-slate-700"
            >
              <summary className="flex cursor-pointer items-center gap-3 flex-wrap">
                <span className="bg-emerald-600 text-white text-xs px-2 py-1 rounded font-bold">
                  本周
                </span>
                <span className="text-slate-200 font-medium flex-1">
                  {w.focus}
                </span>
                <span className="text-xs text-slate-500">
                  共 {w.tasks.length} 天
                </span>
              </summary>
              <div className="mt-4 space-y-3">
                {w.tasks.map((t, i) => (
                  <details key={i} className="rounded-lg border border-slate-700 bg-slate-900/40">
                    <summary className="cursor-pointer p-3 text-sm text-slate-200">
                      {t.day} · {t.topic} · 预计 {t.time_minutes} 分钟
                      {progress.some(item => item.week_index === weekIndex && item.task_index === i) && <span className="ml-2 text-emerald-300">{progress.find(item => item.week_index === weekIndex && item.task_index === i)?.status === "verified" ? "已验收" : "已记录"}</span>}
                    </summary>
                    <TaskBlock task={t} gapMap={gapMap}
                      progress={progress.find(item => item.week_index === weekIndex && item.task_index === i)}
                      onSave={assessmentId ? async (evidence, status) => {
                        const item = await saveLearningProgress(assessmentId, weekIndex, i, evidence, status);
                        setProgress(current => [...current.filter(old => old.week_index !== weekIndex || old.task_index !== i), item]);
                      } : undefined} />
                  </details>
                ))}
              </div>
            </details>
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

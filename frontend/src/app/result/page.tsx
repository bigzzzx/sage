"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import RadarChart from "@/components/RadarChart";
import LearningPlanCard from "@/components/LearningPlanCard";
import DiagnosisPanel from "@/components/DiagnosisPanel";
import AgentTracePanel from "@/components/AgentTracePanel";
import type { AssessmentResult } from "@/lib/api";

const LEVEL_COLOR: Record<string, string> = {
  L1: "bg-rose-600",
  L2: "bg-amber-600",
  L3: "bg-emerald-600",
};

const LEVEL_DESC: Record<string, string> = {
  L1: "入门级 · 需系统学习",
  L2: "熟练级 · 有实战经验",
  L3: "专家级 · 深入理解原理",
};

export default function ResultPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getStoredUser()) router.push("/login");
  }, [router]);
  const [result, setResult] = useState<AssessmentResult | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem("sage_result");
    if (raw) {
      try {
        setResult(JSON.parse(raw));
      } catch {
        setResult(null);
      }
    }
  }, []);

  if (!result) {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-200 flex items-center justify-center">
        <div className="text-center space-y-4">
          <p>暂无测评结果</p>
          <Link
            href="/assessment"
            className="inline-block px-5 py-2 bg-emerald-600 hover:bg-emerald-500 rounded text-white"
          >
            去测评
          </Link>
        </div>
      </main>
    );
  }

  const plan = result.learning_plan;
  // 把后端 capability radar 转换成 RadarChart 期望的格式
  const radarData = (result.capability_radar || []).map((c) => ({
    dimension_id: c.capability_id,
    dimension_name: c.capability_name,
    score: c.score,
  }));

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="max-w-5xl mx-auto space-y-8">
        {/* 顶部总览 */}
        <header className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <div className="text-xs text-emerald-400 mb-1">
                {result.service_name} 测评结果
              </div>
              <h1 className="text-3xl font-bold mb-1">📊 测评结果</h1>
              <p className="text-slate-400 text-sm">User: {result.user_id}</p>
            </div>
            <div className="flex items-center gap-6">
              <div className="text-center">
                <div className="text-xs text-slate-400 mb-1">选择题</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {result.choice_score}
                </div>
              </div>
              <div className="text-center">
                <div className="text-xs text-slate-400 mb-1">总体评级</div>
                <div
                  className={`inline-block px-4 py-1.5 rounded text-white text-xl font-bold ${LEVEL_COLOR[result.overall_level] || "bg-slate-600"}`}
                >
                  {result.overall_level}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  {LEVEL_DESC[result.overall_level]}
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* 雷达图 + 维度详情 */}
        <section className="grid md:grid-cols-2 gap-6">
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="text-lg font-semibold mb-4">能力雷达图</h2>
            <p className="text-xs text-slate-500 mb-2">
              本次仅覆盖 {result.service_name} 的能力点。完整职业方向雷达图请查看{" "}
              <Link href="/profile" className="text-emerald-400 hover:underline">
                我的能力档案 →
              </Link>
            </p>
            <RadarChart data={radarData} />
          </div>
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="text-lg font-semibold mb-4">各能力点得分</h2>
            <div className="space-y-3">
              {result.capability_radar
                .slice()
                .sort((a, b) => a.score - b.score)
                .map((r) => {
                  const pct = (r.score / 5) * 100;
                  const isLowSample = (result.capability_excluded || []).includes(
                    r.capability_name,
                  );
                  const color =
                    r.score < 2
                      ? "bg-rose-500"
                      : r.score < 3.5
                        ? "bg-amber-500"
                        : "bg-emerald-500";
                  return (
                    <div key={r.capability_id}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-slate-200 flex items-center gap-2">
                          {r.capability_name}
                          {isLowSample && (
                            <span
                              className="text-xs text-slate-500 bg-slate-700/60 px-1.5 py-0.5 rounded"
                              title="该能力点只有 1 道题，得分仅供参考"
                            >
                              参考分
                            </span>
                          )}
                        </span>
                        <span className="text-slate-400">{r.score}/5</span>
                      </div>
                      <div className="h-2 bg-slate-900 rounded">
                        <div
                          className={`h-full rounded ${color} ${isLowSample ? "opacity-50" : ""} transition-all`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
            </div>
            {(result.capability_excluded || []).length > 0 && (
              <p className="text-xs text-slate-500 mt-4 leading-relaxed">
                💡 标记为「参考分」的能力点本次仅有 1 道题，分数已做保守化处理。
              </p>
            )}
          </div>
        </section>

        {/* 知识盲区诊断（多 Agent 流水线产出） */}
        {result.diagnosis && result.diagnosis.length > 0 && (
          <DiagnosisPanel gaps={result.diagnosis} />
        )}

        {/* 后测前后对比 */}
        {result.prev_capability_radar && result.prev_capability_radar.length > 0 && (
          <section className="bg-slate-800 rounded-xl p-6 border border-emerald-700">
            <h2 className="text-lg font-semibold mb-4">📈 前后对比（后测 vs 前测）</h2>
            <div className="space-y-3">
              {result.capability_radar.map((curr) => {
                const prev = result.prev_capability_radar?.find(
                  (p) =>
                    p.capability_id === curr.capability_id ||
                    p.capability_name === curr.capability_name,
                );
                const prevScore = prev?.score ?? 0;
                const diff = curr.score - prevScore;
                const diffColor =
                  diff > 0
                    ? "text-emerald-400"
                    : diff < 0
                      ? "text-rose-400"
                      : "text-slate-400";
                return (
                  <div
                    key={curr.capability_id}
                    className="flex items-center gap-3"
                  >
                    <span className="text-sm text-slate-200 w-48 shrink-0 truncate">
                      {curr.capability_name}
                    </span>
                    <span className="text-xs text-slate-500 w-12">
                      {prevScore}/5
                    </span>
                    <span className="text-slate-500">→</span>
                    <span className="text-xs text-slate-200 w-12 font-semibold">
                      {curr.score}/5
                    </span>
                    <span className={`text-xs font-bold ${diffColor}`}>
                      {diff > 0
                        ? `+${diff.toFixed(1)}`
                        : diff < 0
                          ? diff.toFixed(1)
                          : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* 学习计划 */}
        {plan && (
          <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="text-lg font-semibold mb-2">📚 个性化学习计划</h2>
            <p className="text-xs text-slate-500 mb-4">
              这份计划会保留在「我的能力档案」里，随时可以回来查看；完成后测验证后自动归档
            </p>
            <LearningPlanCard plan={plan} gaps={result.diagnosis || []} />
          </section>
        )}

        {/* 完整回顾 */}
        <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">📝 完整回顾</h2>
          <div className="space-y-4">
            {(result.questions || []).map((q, idx) => {
              const r = result.question_results.find(
                (x) => x.question_id === q.id,
              );
              if (!r) return null;

              return (
                <div
                  key={q.id}
                  className="bg-slate-900/40 rounded-lg p-4 border border-slate-700"
                >
                  <div className="flex items-center justify-between mb-2 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-slate-500">
                        Q{idx + 1}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 rounded ${
                          q.type === "choice"
                            ? "bg-emerald-600/30 text-emerald-300"
                            : "bg-amber-600/30 text-amber-300"
                        }`}
                      >
                        {q.type === "choice" ? "选择" : "开放"} ·{" "}
                        {q.difficulty || "?"}
                      </span>
                      <span className="text-slate-500 truncate max-w-[18rem]">
                        {q.dimension_id}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {r.type === "choice" ? (
                        <span
                          className={
                            r.is_correct
                              ? "text-emerald-400"
                              : "text-rose-400"
                          }
                        >
                          {r.is_correct ? "✅ 正确" : "❌ 错误"}
                        </span>
                      ) : (
                        <>
                          <span className="text-amber-400">
                            {r.total_score}/25
                          </span>
                          {r.level && (
                            <span
                              className={`text-white text-xs px-2 py-0.5 rounded ${LEVEL_COLOR[r.level] || "bg-slate-600"}`}
                            >
                              {r.level}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>

                  <p className="text-slate-100 mb-3 text-sm leading-relaxed whitespace-pre-wrap">
                    {q.question}
                  </p>

                  {q.type === "choice" && (
                    <div className="space-y-1.5 mb-3">
                      {q.options.map((opt, i) => {
                        const letter = String.fromCharCode(65 + i);
                        const isCorrect = letter === q.correct_answer;
                        const display = opt.replace(
                          /^[A-Da-d][.、)\s]\s*/,
                          "",
                        );
                        return (
                          <div
                            key={i}
                            className={`flex items-start gap-2 text-sm p-2 rounded ${
                              isCorrect
                                ? "bg-emerald-500/10 text-emerald-200"
                                : "text-slate-400"
                            }`}
                          >
                            <span
                              className={`font-bold w-5 ${isCorrect ? "text-emerald-400" : "text-slate-500"}`}
                            >
                              {letter}.
                            </span>
                            <span className="flex-1">{display}</span>
                            {isCorrect && (
                              <span className="text-xs">正确答案</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {q.type === "choice" && q.explanation && (
                    <div className="text-xs text-slate-400 bg-slate-950/50 p-2 rounded border-l-2 border-emerald-500 mb-2">
                      <span className="text-emerald-400 mr-1">解析：</span>
                      {q.explanation}
                    </div>
                  )}

                  {q.type === "open" &&
                    q.scoring_rubric &&
                    q.scoring_rubric.length > 0 && (
                      <details className="text-xs mb-2">
                        <summary className="cursor-pointer text-slate-400 hover:text-slate-200 mb-1">
                          查看评分要点（{q.scoring_rubric.length} 个）
                        </summary>
                        <ul className="space-y-1 mt-1 ml-3">
                          {q.scoring_rubric.map((p, i) => (
                            <li
                              key={i}
                              className="text-slate-400 list-disc list-inside"
                            >
                              {p}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}

                  {r.feedback && (
                    <div className="text-xs text-slate-300 bg-amber-950/30 p-2 rounded border-l-2 border-amber-500">
                      <span className="text-amber-400 mr-1">AI 反馈：</span>
                      {r.feedback}
                    </div>
                  )}

                  {r.type === "open" && r.score_detail && (
                    <div className="mt-2 grid grid-cols-3 sm:grid-cols-5 gap-1 text-[10px] text-center">
                      {(() => {
                        const LABELS: Record<string, string> = {
                          accuracy: "准确性",
                          completeness: "完整性",
                          clarity: "清晰度",
                          logical_flow: "逻辑条理",
                          technical_depth: "技术深度",
                          systematic_approach: "排查思路",
                          root_cause_identification: "根因定位",
                          solution_feasibility: "方案可行",
                          before_after_clarity: "前后对比",
                          diagnostic_approach: "诊断思路",
                          depth: "深度",
                          practicality: "实操性",
                        };
                        const detail = r.score_detail as unknown as Record<string, number>;
                        return Object.entries(detail)
                          .filter(([k, v]) => typeof v === "number" && v > 0 && k in LABELS)
                          .map(([k, v]) => (
                            <div
                              key={k}
                              className="bg-slate-800/60 py-1 rounded"
                            >
                              <div className="text-amber-400 font-bold">
                                {v}/5
                              </div>
                              <div className="text-slate-500">{LABELS[k]}</div>
                            </div>
                          ));
                      })()}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* AI 思考过程（多 Agent 协作 trace） */}
        {result.agent_trace && result.agent_trace.length > 0 && (
          <AgentTracePanel trace={result.agent_trace} />
        )}

        <div className="flex gap-4 flex-wrap">
          <Link
            href="/assessment"
            className="flex-1 min-w-[200px] py-3 bg-slate-700 hover:bg-slate-600 text-center rounded text-white"
          >
            重新测评
          </Link>
          {result.assessment_id && result.kind !== "post" && (
            <Link
              href={`/post-test?prev=${result.assessment_id}`}
              className="flex-1 min-w-[200px] py-3 bg-amber-600 hover:bg-amber-500 text-center rounded text-white font-medium"
            >
              📝 学完后测验证 →
            </Link>
          )}
          <Link
            href="/profile"
            className="flex-1 min-w-[200px] py-3 bg-emerald-600 hover:bg-emerald-500 text-center rounded text-white font-medium"
          >
            🎯 我的能力档案 →
          </Link>
        </div>
      </div>
    </main>
  );
}

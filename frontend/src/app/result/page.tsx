"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import RadarChart from "@/components/RadarChart";
import LearningPlanCard from "@/components/LearningPlanCard";
import DiagnosisPanel from "@/components/DiagnosisPanel";
import AgentTracePanel from "@/components/AgentTracePanel";
import QualityFeedbackForm from "@/components/QualityFeedbackForm";
import { fetchAssessmentResult, retryLearning, type AssessmentResult } from "@/lib/api";

const LEVEL_COLOR: Record<string, string> = {
  L1: "bg-rose-600",
  L2: "bg-amber-600",
  L3: "bg-emerald-600",
};

const LEVEL_DESC: Record<string, string> = {
  L1: "本次题目仍需巩固",
  L2: "本次题目表现中等",
  L3: "本次题目表现较好",
};

export default function ResultPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getStoredUser()) router.push("/login");
  }, [router]);
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) { queueMicrotask(() => setError("暂无测评结果")); return; }
    fetchAssessmentResult(id).then(setResult).catch((reason) => setError(String(reason)));
  }, []);

  if (!result) {
    return (
      <main className="min-h-screen bg-slate-900 text-slate-200 flex items-center justify-center">
        <div className="text-center space-y-4">
          <p>{error || "正在读取测评报告…"}</p>
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
  const answerMap = new Map((result.answers || []).map(item => [item.question_id, item.answer]));
  const reviewPassed = result.plan_review?.status === "passed";
  const weakestCapability = [...(result.capability_radar || [])]
    .filter(item => item.sample_count >= 2 && item.score < 3.5)
    .sort((a, b) => a.score - b.score)[0];
  const practiceParams = new URLSearchParams({ service: result.service_id });
  if (result.assessment_id) practiceParams.set("from", result.assessment_id);
  const assessmentParams = new URLSearchParams(practiceParams);
  if (weakestCapability) assessmentParams.set("capability", weakestCapability.capability_id);
  const questionCount = result.questions?.length || 0;
  const hasHistoricalScoringWarning = result.question_results.some(item => item.feedback?.includes("历史评分未追溯修改"));
  const hasMappingWarning = result.questions.some(question => !!question.mapping_warning);
  // 把后端 capability radar 转换成 RadarChart 期望的格式
  const radarData = (result.capability_radar || []).map((c) => ({
    dimension_id: c.capability_id,
    dimension_name: c.capability_name,
    score: c.score,
  }));

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="sage-content sage-content--reading mx-auto max-w-5xl space-y-8">
        {/* 顶部总览 */}
        <header className="bg-slate-800 rounded-xl p-6 border border-slate-700">
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <div className="text-xs text-emerald-400 mb-1">
                {result.service_name} 测评结果
              </div>
              <h1 className="sage-page-title text-3xl font-bold mb-1">📊 测评结果</h1>
              <p className="sage-page-description text-slate-400 text-sm">本次共 {questionCount} 题，结果仅代表本次所测考点</p>
              {result.record_origin === "agent_test" && <p className="mt-2 text-sm text-amber-300">代答测试记录 · 仅用于检查出题和报告效果，不计入你的能力档案或学习进度</p>}
              {result.blueprint && <p className="mt-2 text-xs text-slate-400">
                {result.blueprint.scope === "focused" ? "专项" : "综合"} · {result.blueprint.question_count} 题 · {result.blueprint.difficulty_profile === "foundation" ? "基础优先" : result.blueprint.difficulty_profile === "advanced" ? "进阶优先" : "均衡"}
                <span className="ml-2 text-amber-300">不同题量或范围的结果不宜直接比较</span>
              </p>}
            </div>
            <div className="flex items-center gap-6">
              <div className="text-center">
                <div className="text-xs text-slate-400 mb-1">选择题</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {result.choice_score}
                </div>
              </div>
              <div className="text-center">
                <div className="text-xs text-slate-400 mb-1">本次答题表现</div>
                <div
                  className={`inline-block px-4 py-1.5 rounded text-white text-xl font-bold ${result.rating_reliable ? LEVEL_COLOR[result.overall_level] || "bg-slate-600" : "bg-slate-600"}`}
                >
                  {result.rating_reliable ? result.overall_level : "覆盖不足，暂不定级"}
                </div>
                <div className="text-xs text-slate-400 mt-1">
                  {typeof result.overall_avg === "number" ? `${result.overall_avg.toFixed(2)}/5 · 按全部题目计算` : ""}
                  {result.rating_reliable && ` · ${LEVEL_DESC[result.overall_level]}`}
                </div>
                {result.rating_reason && <p className="mt-2 max-w-xs text-xs leading-5 text-amber-300">{result.rating_reason}</p>}
                {result.scoring_version === "legacy_or_mixed" && <p className="mt-1 max-w-xs text-xs leading-5 text-slate-400">历史开放题保留原评分；定级按当前题型覆盖标准展示。</p>}
              </div>
            </div>
          </div>
        </header>

        <nav aria-label="报告目录" className="flex flex-wrap gap-2 rounded-xl border border-slate-700 bg-slate-800/60 p-3 text-xs">
          <span className="px-2 py-2 text-slate-400">跳转到</span>
          <a href="#capabilities" className="rounded-lg bg-slate-900 px-3 py-2 text-sky-300 hover:bg-slate-700">能力概览</a>
          {result.learning_plan && <a href="#learning-plan" className="rounded-lg bg-slate-900 px-3 py-2 text-sky-300 hover:bg-slate-700">学习计划</a>}
          {result.rag_sources?.length ? <a href="#sources" className="rounded-lg bg-slate-900 px-3 py-2 text-sky-300 hover:bg-slate-700">参考资料</a> : null}
          <a href="#questions" className="rounded-lg bg-slate-900 px-3 py-2 text-sky-300 hover:bg-slate-700">逐题回顾</a>
        </nav>

        {hasHistoricalScoringWarning && <p className="rounded-lg border border-amber-700 bg-amber-950/30 p-3 text-sm text-amber-200">
          这份历史报告有事实复核提示；原始分数未追溯改写，不能把旧评分当作已复核结论。请看下方对应题目的更正。
        </p>}
        {hasMappingWarning && <p className="rounded-lg border border-amber-700 bg-amber-950/30 p-3 text-sm text-amber-200">这份历史报告有题目与能力点错配；原始分数和题目未追溯修改。请以题目回顾为准，不要把对应能力点分数当作已核实的掌握程度。</p>}

        {/* 雷达图 + 维度详情 */}
        <section id="capabilities" className="grid scroll-mt-24 gap-6 md:grid-cols-2">
          <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="text-lg font-semibold mb-4">能力雷达图</h2>
            <p className="text-xs text-slate-500 mb-2">
              本次仅覆盖 {result.service_name} 的能力点。完整职业方向雷达图请查看{" "}
              <Link href="/profile" className="text-emerald-400 hover:underline">
                我的能力档案 →
              </Link>
            </p>
            {radarData.length >= 3 ? <RadarChart data={radarData} /> : <p className="rounded-lg bg-slate-900/60 p-4 text-sm text-slate-400">本次有证据的能力点少于 3 个，雷达图无法清楚呈现；请查看右侧能力点得分。</p>}
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
        {result.comparison && (
          <section className="bg-slate-800 rounded-xl p-6 border border-emerald-700">
            <h2 className="text-lg font-semibold mb-4">📈 前后对比（后测 vs 前测）</h2>
            {!result.comparison.comparable && <p className="rounded-lg border border-amber-700 bg-amber-950/30 p-3 text-sm text-amber-200">本次仅展示两次答题结果，不计算成长幅度：{result.comparison.reason}</p>}
            {result.comparison.comparable && result.prev_capability_radar && <>
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
            </>}
          </section>
        )}

        {/* 学习计划 */}
        {plan && (
          <section id="learning-plan" className="scroll-mt-24 bg-slate-800 rounded-xl p-6 border border-slate-700">
            <h2 className="text-lg font-semibold mb-2">📚 个性化学习计划</h2>
            <p className="text-xs text-slate-500 mb-4">
              这份计划会保留在「我的能力档案」里，随时可以回来查看；完成后测验证后自动归档
            </p>
            {!reviewPassed && <p className="mb-4 rounded-lg border border-amber-700 bg-amber-950/30 p-3 text-sm text-amber-200">
              计划仍有待复核的问题。请先查看下方具体审查意见，资源变更类实验暂按“待确认”处理。
            </p>}
            {reviewPassed ? (
              <LearningPlanCard plan={plan} gaps={result.diagnosis || []} assessmentId={result.assessment_id}
                showOverallAssessment={!!result.rating_reliable} />
            ) : (
              <details className="rounded-lg border border-slate-700 p-4">
                <summary className="cursor-pointer text-amber-200">查看待复核学习计划</summary>
                <div className="mt-4"><LearningPlanCard plan={plan} gaps={result.diagnosis || []}
                  showOverallAssessment={false} /></div>
              </details>
            )}
          </section>
        )}

        {result.model_id && <p className="text-xs text-slate-400">本次测评模型：{result.model_id}</p>}
        {plan?.deferred_gap_ids && plan.deferred_gap_ids.length > 0 && (
          <p className="text-sm text-amber-200">
            受学习时间限制，以下知识缺口已延后：{plan.deferred_gap_ids.join("、")}。
            建议在后续学习周期继续处理。
          </p>
        )}
        {result.kind === "pre" && !result.learning_plan && result.plan_review && (
          <p className="text-sm text-slate-300">
            未生成补弱计划：{result.plan_review.remaining_issues?.length
              ? "部分答案仍需人工复核，暂不能给出可靠的知识缺口。"
              : "本次测评未识别出有证据支持的知识缺口。"}
          </p>
        )}
        {result.kind === "pre" && !result.learning_plan && !result.plan_review && result.assessment_id && (
          <section className="bg-slate-800 rounded-xl p-5 border border-amber-800" aria-label="学习计划恢复">
            <p className="text-amber-200 text-sm">评分已保存，学习计划尚未完成。</p>
            <button type="button" disabled={retrying}
              onClick={async () => {
                setRetrying(true);
                setError(null);
                try { setResult(await retryLearning(result.assessment_id!)); }
                catch (reason) { setError(String(reason)); }
                finally { setRetrying(false); }
              }}
              className="mt-3 px-4 py-2 rounded bg-amber-600 hover:bg-amber-500 disabled:opacity-50">
              {retrying ? "正在恢复…" : "继续生成学习计划"}
            </button>
            {error && <p role="alert" className="mt-2 text-rose-300 text-sm">{error}</p>}
          </section>
        )}
        {result.plan_review && (
          <section className="bg-slate-800 rounded-xl p-5 border border-slate-700" aria-label="学习计划审核">
            <h2 className="text-base font-semibold mb-2">学习计划审核</h2>
            <p className={result.plan_review.status === "passed" ? "text-emerald-300 text-sm" : "text-amber-300 text-sm"}>
              {result.plan_review.status === "passed" ? "自动流程检查通过；技术内容仍需人工核验" : result.plan_review.status === "unverified" ? "自动审查未完成，建议人工复核" : "仍有待人工复核的问题"}
              {result.plan_review.revision_attempted && ` · 已尝试一次修订${result.plan_review.revision_applied ? "并采用修订版" : "，保留原计划"}`}
            </p>
            {result.plan_review.remaining_issues?.length > 0 && (
              <ul className="mt-2 list-disc list-inside text-sm text-slate-300">
                {result.plan_review.remaining_issues.map((issue, index) => <li key={`${issue}-${index}`}>{issue}</li>)}
              </ul>
            )}
            {result.plan_review.critique?.summary && <p className="mt-2 text-xs text-slate-400">审查意见：{result.plan_review.critique.summary}</p>}
          </section>
        )}

        {result.rag_sources && result.rag_sources.length > 0 && (
          <section id="sources" className="scroll-mt-24 bg-slate-800 rounded-xl p-6 border border-sky-800/70">
            <div className="flex items-baseline justify-between gap-3 flex-wrap mb-4">
              <h2 className="text-lg font-semibold">检索依据</h2>
              <span className="text-xs text-sky-300">
                {result.rag_sources.some((source) => source.retrieval_method === "hybrid_rrf" || source.retrieval_method === "chroma_hybrid_rerank") ? "向量＋关键词融合 · 学习计划参考" : result.rag_sources.some((source) => source.retrieval_method !== "curated") ? "BM25 关键词检索 · 学习计划参考" : "策展官方参考资料 · 不代表逐条验证生成内容"}
              </span>
            </div>
            <div className="space-y-3">
              {result.rag_sources.map((source) => (
                <div key={source.document_id} className="border border-slate-700 bg-slate-900/40 p-3 rounded-lg">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    {source.url ? (
                      <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-sm text-sky-300 hover:underline">
                        {source.title}
                      </a>
                    ) : <span className="text-sm text-slate-200">{source.title}</span>}
                    <span className="text-[10px] text-slate-500">{source.source_type}{source.retrieval_method === "curated" ? " · 策展来源" : ` · 相对排序 ${source.score}`}</span>
                  </div>
                  {source.excerpt && <p className="text-xs text-slate-400 mt-2 leading-relaxed line-clamp-3">{source.excerpt}</p>}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 完整回顾 */}
        <section id="questions" className="scroll-mt-24 bg-slate-800 rounded-xl p-6 border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">📝 完整回顾</h2>
          <div className="space-y-4">
            {(result.questions || []).map((q, idx) => {
              const r = result.question_results.find(
                (x) => x.question_id === q.id,
              );
              const userAnswer = answerMap.get(q.id) || "";
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
                              题目难度 {r.level}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>

                  <p className="text-slate-100 mb-3 text-sm leading-relaxed whitespace-pre-wrap">
                    {q.question}
                  </p>
                  <div className="mb-3 rounded bg-slate-800/70 p-3 text-sm text-slate-200 whitespace-pre-wrap">
                    <span className="text-sky-300">你的回答：</span>{q.type === "choice" ? `${userAnswer || "未作答"} · ${q.options?.[userAnswer.toUpperCase().charCodeAt(0) - 65] || ""}` : userAnswer || "未作答"}
                  </div>
                  {q.mapping_warning && <p className="mb-3 rounded border border-amber-700/60 p-2 text-xs text-amber-300">{q.mapping_warning}</p>}

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

                  {q.source_refs && q.source_refs.length > 0 && (
                    <details className="text-xs mb-2">
                      <summary className="cursor-pointer text-sky-300">查看模型标注的官方资料（关联关系仍需核验）</summary>
                      <ul className="mt-2 space-y-1 list-disc list-inside text-slate-400">
                        {q.source_refs.map((source) => (
                          <li key={source.id}>
                            <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-sky-300 hover:underline">{source.id}</a>
                            <span> · {source.fact}</span>
                          </li>
                        ))}
                      </ul>
                    </details>
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
                      <span className="text-amber-400 mr-1">评分与复核反馈：</span>
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
                  {result.assessment_id && <QualityFeedbackForm recordType="assessment" recordId={result.assessment_id} questionId={q.id} />}
                </div>
              );
            })}
          </div>
        </section>

        {/* 工作流步骤记录，不是模型私有思维链 */}
        {result.agent_trace && result.agent_trace.length > 0 && (
          <AgentTracePanel trace={result.agent_trace} />
        )}

        {result.assessment_id && <QualityFeedbackForm recordType="assessment" recordId={result.assessment_id} />}

        <div className="flex gap-4 flex-wrap">
          <Link href={`/assessment?${assessmentParams}`} className="flex-1 min-w-[200px] py-3 bg-sky-700 hover:bg-sky-600 text-center rounded text-white">
            {weakestCapability ? `针对性再测 · ${weakestCapability.capability_name}` : "再测本服务"} →
          </Link>
          <Link href={`/practice?${practiceParams}`} className="flex-1 min-w-[200px] py-3 bg-slate-700 hover:bg-slate-600 text-center rounded text-white">
            练习 {result.service_name} 客户工单 →
          </Link>
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

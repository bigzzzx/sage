"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import TrackRadarChart from "@/components/TrackRadarChart";
import LearningPlanCard from "@/components/LearningPlanCard";
import {
  fetchActivePlans,
  fetchTaxonomy,
  fetchUserTrackRadar,
  type ActivePlan,
  type FullTaxonomy,
  type UserTrackRadar,
} from "@/lib/api";

const LEVEL_COLOR: Record<string, string> = {
  L1: "bg-rose-600",
  L2: "bg-amber-600",
  L3: "bg-emerald-600",
};

export default function ProfilePage() {
  const router = useRouter();
  const user = getStoredUser();

  useEffect(() => {
    if (!user) router.push("/login");
    else if (user.role === "manager") router.push("/");
  }, [router]);

  const userProfile = user?.current_profile || "big_data";

  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [trackId, setTrackId] = useState(userProfile);
  const [radar, setRadar] = useState<UserTrackRadar | null>(null);
  const [loading, setLoading] = useState(true);
  const [activePlans, setActivePlans] = useState<ActivePlan[]>([]);
  const [expandedPlanId, setExpandedPlanId] = useState<string | null>(null);

  useEffect(() => {
    fetchTaxonomy().then(setTaxonomy);
    fetchActivePlans("demo_user", userProfile).then((plans) => {
      setActivePlans(plans);
      if (plans.length > 0) setExpandedPlanId(plans[0].assessment_id);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchUserTrackRadar("demo_user", trackId)
      .then(setRadar)
      .finally(() => setLoading(false));
  }, [trackId]);

  const tested = (radar?.services || []).filter((s) => s.is_tested);
  const untested = (radar?.services || []).filter((s) => !s.is_tested);
  const avgScore =
    tested.length > 0
      ? Math.round((tested.reduce((a, s) => a + s.score, 0) / tested.length) * 10) / 10
      : 0;

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="max-w-5xl mx-auto space-y-6">
        <header className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-3xl font-bold mb-1">🎯 我的能力档案</h1>
            <p className="text-slate-400">
              覆盖整个职业方向的能力图谱 · 用户：demo_user
            </p>
          </div>
          <div className="flex gap-2">
            <Link
              href="/assessment"
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded text-white text-sm"
            >
              + 新测评
            </Link>
          </div>
        </header>

        {/* 进行中的学习计划 */}
        {activePlans.length > 0 && (
          <section className="bg-slate-800 rounded-xl p-6 border border-emerald-700/40">
            <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
              <h2 className="text-lg font-semibold">📚 进行中的学习计划</h2>
              <span className="text-xs text-slate-500">
                完成对应的后测验证后会自动归档
              </span>
            </div>
            <p className="text-xs text-slate-500 mb-4">
              每个服务最多保留一份最新计划
            </p>

            <div className="space-y-3">
              {activePlans.map((p) => {
                const isOpen = expandedPlanId === p.assessment_id;
                const created = p.created_at
                  ? new Date(p.created_at).toLocaleString("zh-CN", {
                      year: "numeric",
                      month: "2-digit",
                      day: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "";
                const totalTasks = (p.learning_plan?.weekly_plan || []).reduce(
                  (a, w) => a + (w.tasks?.length || 0),
                  0,
                );
                const totalMin = (p.learning_plan?.weekly_plan || []).reduce(
                  (a, w) =>
                    a +
                    (w.tasks || []).reduce(
                      (b, t) => b + (t.time_minutes || 0),
                      0,
                    ),
                  0,
                );
                return (
                  <div
                    key={p.assessment_id}
                    className="bg-slate-900/40 rounded-lg border border-slate-700 overflow-hidden"
                  >
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedPlanId(isOpen ? null : p.assessment_id)
                      }
                      className="w-full p-4 flex items-center gap-4 hover:bg-slate-800/40 transition-colors text-left"
                    >
                      <span className="text-2xl">{p.icon || "📦"}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="font-semibold text-slate-100">
                            {p.service_name}
                          </span>
                          <span
                            className={`text-[10px] text-white px-1.5 py-0.5 rounded ${LEVEL_COLOR[p.overall_level] || "bg-slate-600"}`}
                          >
                            {p.overall_level}
                          </span>
                          <span className="text-[10px] bg-emerald-600/20 text-emerald-300 px-1.5 py-0.5 rounded">
                            待后测
                          </span>
                        </div>
                        <div className="text-xs text-slate-400 truncate">
                          {p.learning_plan?.plan_name || "学习计划"}
                        </div>
                        <div className="text-[11px] text-slate-500 mt-1">
                          {created} · {totalTasks} 个任务 · 共 {totalMin} 分钟
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Link
                          href={`/post-test?prev=${p.assessment_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="px-3 py-1.5 text-xs bg-amber-600 hover:bg-amber-500 rounded text-white whitespace-nowrap"
                        >
                          后测验证 →
                        </Link>
                        <span className="text-slate-500 text-sm w-4 text-center">
                          {isOpen ? "▾" : "▸"}
                        </span>
                      </div>
                    </button>
                    {isOpen && p.learning_plan && (
                      <div className="p-4 border-t border-slate-700 bg-slate-950/30">
                        <LearningPlanCard
                          plan={p.learning_plan}
                          gaps={p.diagnosis || []}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {loading ? (
          <p className="text-slate-400 text-center py-12">加载中…</p>
        ) : !radar ? (
          <p className="text-slate-400 text-center py-12">暂无数据</p>
        ) : (
          <>
            {/* KPI */}
            <section className="grid grid-cols-3 gap-4">
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">已测服务</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {tested.length} / {radar.services.length}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">平均能力分</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {avgScore}/5
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">最强 / 最弱</div>
                <div className="text-sm font-bold text-slate-100 leading-tight">
                  {tested.length > 0
                    ? `${tested.slice().sort((a, b) => b.score - a.score)[0].service_name} / ${tested
                        .slice()
                        .sort((a, b) => a.score - b.score)[0].service_name}`
                    : "—"}
                </div>
              </div>
            </section>

            {/* 雷达图 */}
            <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <h2 className="text-lg font-semibold mb-4">
                {radar.icon} {radar.track_name} 能力雷达
              </h2>
              <TrackRadarChart data={radar.services} />
              {untested.length > 0 && (
                <p className="text-xs text-slate-500 mt-2">
                  💡 灰色未填充的轴表示尚未测评的服务，先测一次它们就会亮起来。
                </p>
              )}
            </section>

            {/* 服务详情列表 */}
            <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <h2 className="text-lg font-semibold mb-4">服务能力详情</h2>
              <div className="space-y-3">
                {radar.services
                  .slice()
                  .sort((a, b) => Number(b.is_tested) - Number(a.is_tested) || b.score - a.score)
                  .map((s) => {
                    const pct = (s.score / 5) * 100;
                    const color =
                      !s.is_tested
                        ? "bg-slate-700"
                        : s.score < 2
                          ? "bg-rose-500"
                          : s.score < 3.5
                            ? "bg-amber-500"
                            : "bg-emerald-500";
                    return (
                      <div
                        key={s.service_id}
                        className={`p-4 rounded-lg border ${
                          s.is_tested
                            ? "bg-slate-900/40 border-slate-700"
                            : "bg-slate-900/20 border-slate-800"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xl">{s.icon}</span>
                            <span className="font-medium">{s.service_name}</span>
                            {false && (
                              <span className="text-[10px] bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded">
                                示例
                              </span>
                            )}
                            {!s.is_tested && (
                              <span className="text-[10px] bg-slate-700 text-slate-400 px-1.5 py-0.5 rounded">
                                未测评
                              </span>
                            )}
                          </div>
                          <span className="text-sm text-slate-300">
                            {s.is_tested ? `${s.score}/5` : "—"}
                          </span>
                        </div>
                        <div className="h-2 bg-slate-900 rounded">
                          <div
                            className={`h-full rounded ${color} transition-all`}
                            style={{ width: `${s.is_tested ? pct : 0}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}

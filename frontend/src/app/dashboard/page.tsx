"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import HeatmapChart, { type HeatmapPoint } from "@/components/HeatmapChart";
import {
  fetchTaxonomy,
  fetchTeamRadar,
  fetchUserTrackRadar,
  type FullTaxonomy,
  type TeamMemberRadar,
  type UserTrackRadar,
} from "@/lib/api";

/**
 * 经理看板：团队能力热力图 + 短板与培训建议。
 *
 * 数据策略：
 * - 从后端 /team-radar 拉取所有 member 的真实 track-radar 数据
 * - "我"：管理员自己的数据
 * - 无数据的 member 仍显示（score=0），确保团队全员可见
 */

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getStoredUser>>(null);

  useEffect(() => {
    const u = getStoredUser();
    if (!u) {
      router.push("/login");
      return;
    }
    if (u.role !== "manager") {
      router.push("/");
      return;
    }
    setUser(u);
  }, [router]);

  const trackId = user?.current_profile || "big_data";

  const [taxonomy, setTaxonomy] = useState<FullTaxonomy | null>(null);
  const [teamMembers, setTeamMembers] = useState<TeamMemberRadar[]>([]);
  const [meRadar, setMeRadar] = useState<UserTrackRadar | null>(null);
  const [heatmap, setHeatmap] = useState<HeatmapPoint[]>([]);

  // 只在 user 加载完成后才拉数据，避免竞态
  useEffect(() => {
    if (!user) return;
    fetchTaxonomy().then(setTaxonomy);
    fetchUserTrackRadar(user.user_id, trackId).then(setMeRadar);
    fetchTeamRadar(trackId).then(setTeamMembers);
  }, [user, trackId]);

  useEffect(() => {
    if (!taxonomy || !user) return;
    const track = taxonomy.tracks.find((t) => t.id === trackId);
    if (!track) return;

    const services = track.services;
    const points: HeatmapPoint[] = [];

    // 所有 member 的真实数据
    teamMembers.forEach((m) => {
      const memberName = m.display_name || m.username;
      if (m.radar && m.radar.services) {
        m.radar.services.forEach((s) => {
          points.push({
            member: memberName,
            dimension: s.service_name,
            score: s.is_tested ? s.score : 0,
          });
        });
      } else {
        // 没有 radar 数据的成员，每个 service 都是 0
        services.forEach((s) => {
          points.push({ member: memberName, dimension: s.name, score: 0 });
        });
      }
    });

    // "我"（管理员自己）— 真实数据
    if (meRadar) {
      meRadar.services.forEach((s) => {
        points.push({
          member: "我",
          dimension: s.service_name,
          score: s.is_tested ? s.score : 0,
        });
      });
    }

    setHeatmap(points);
  }, [taxonomy, meRadar, teamMembers, trackId]);

  // 团队统计
  const stats = (() => {
    if (!taxonomy) return [];
    const track = taxonomy.tracks.find((t) => t.id === trackId);
    if (!track) return [];
    return track.services.map((s) => {
      const scores = heatmap
        .filter((p) => p.dimension === s.name)
        .map((p) => p.score)
        .filter((v) => v > 0); // 排除"未测=0"
      const avg =
        scores.length > 0
          ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 10) / 10
          : 0;
      const weakCount = scores.filter((v) => v < 3).length;
      return { dimensionName: s.name, avg, weakCount };
    });
  })();

  const weakest = stats
    .filter((s) => s.avg > 0)
    .slice()
    .sort((a, b) => a.avg - b.avg)
    .slice(0, 2);

  const teamAvg =
    stats.filter((s) => s.avg > 0).length > 0
      ? Math.round(
          (stats.filter((s) => s.avg > 0).reduce((a, s) => a + s.avg, 0) /
            stats.filter((s) => s.avg > 0).length) *
            10,
        ) / 10
      : 0;

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="max-w-6xl mx-auto space-y-8">
        {!user ? (
          <p className="text-slate-400 text-center py-12">加载中…</p>
        ) : (
        <>
        <header>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="text-3xl font-bold mb-1">📊 团队能力看板</h1>
              <p className="text-slate-400">
                {taxonomy?.tracks.find((t) => t.id === trackId)?.name || trackId} 方向 · 识别团队整体能力分布与短板
              </p>
            </div>
            <Link
              href="/"
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-white text-sm"
            >
              ← 返回首页
            </Link>
          </div>
        </header>

        {!taxonomy ? (
          <p className="text-slate-400 text-center py-12">加载中…</p>
        ) : (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">团队成员</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {teamMembers.length + (meRadar ? 1 : 0)}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">覆盖服务</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {taxonomy.tracks.find((t) => t.id === trackId)?.services
                    .length || 0}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">团队平均分</div>
                <div className="text-2xl font-bold text-amber-400">
                  {teamAvg}/5
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">最薄弱服务</div>
                <div className="text-sm font-bold text-rose-400 leading-tight">
                  {weakest[0]?.dimensionName || "-"}
                </div>
              </div>
            </section>

            <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <h2 className="text-lg font-semibold mb-4">团队能力热力图</h2>
              <HeatmapChart data={heatmap} height={420} />
              <p className="text-xs text-slate-400 mt-2">
                颜色越深绿表示越熟练，越深红表示越薄弱；空白表示未测评
              </p>
            </section>

            <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <h2 className="text-lg font-semibold mb-4">🎯 团队培训建议</h2>
              <div className="grid md:grid-cols-2 gap-4">
                {weakest.map((s) => (
                  <div
                    key={s.dimensionName}
                    className="bg-rose-500/10 border border-rose-500/40 rounded-lg p-4"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-medium text-rose-300">
                        {s.dimensionName}
                      </span>
                      <span className="text-xs text-slate-400">
                        平均 {s.avg}/5
                      </span>
                    </div>
                    <p className="text-sm text-slate-300 mb-3">
                      团队中{" "}
                      <b className="text-rose-300">{s.weakCount}</b>{" "}
                      人在该服务得分低于 3 分，建议组织专项培训。
                    </p>
                    <div className="flex gap-2 flex-wrap">
                      <span className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
                        建议 KB 学习
                      </span>
                      <span className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
                        case 影子跟进
                      </span>
                      <span className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
                        实操 lab
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <h2 className="text-lg font-semibold mb-4">📈 服务排行</h2>
              <div className="space-y-2">
                {stats
                  .filter((s) => s.avg > 0)
                  .slice()
                  .sort((a, b) => b.avg - a.avg)
                  .map((s) => {
                    const pct = (s.avg / 5) * 100;
                    const color =
                      s.avg < 2.5
                        ? "bg-rose-500"
                        : s.avg < 3.5
                          ? "bg-amber-500"
                          : "bg-emerald-500";
                    return (
                      <div
                        key={s.dimensionName}
                        className="flex items-center gap-4"
                      >
                        <span className="text-sm text-slate-200 w-48 shrink-0 truncate">
                          {s.dimensionName}
                        </span>
                        <div className="flex-1 h-3 bg-slate-900 rounded">
                          <div
                            className={`h-full rounded ${color}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-sm text-slate-400 w-12 text-right">
                          {s.avg}/5
                        </span>
                      </div>
                    );
                  })}
              </div>
            </section>
          </>
        )}
        </>
        )}
      </div>
    </main>
  );
}

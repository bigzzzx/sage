"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getStoredUser } from "@/lib/auth";
import HeatmapChart, { type HeatmapPoint } from "@/components/HeatmapChart";
import {
  fetchTeamDashboard,
  type TeamDashboard,
} from "@/lib/api";

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
    queueMicrotask(() => setUser(u));
  }, [router]);

  const trackId = user?.current_profile || "big_data";

  const [dashboard, setDashboard] = useState<TeamDashboard | null>(null);
  const [days, setDays] = useState<0 | 30 | 90>(0);
  const [includeDemo, setIncludeDemo] = useState(false);
  const [enrolledOnly, setEnrolledOnly] = useState(false);
  const [error, setError] = useState("");
  const [heatmap, setHeatmap] = useState<HeatmapPoint[]>([]);
  const openMember = useCallback((id: string) => router.push(`/dashboard/members/${encodeURIComponent(id)}`), [router]);

  // 只在 user 加载完成后才拉数据，避免竞态
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    fetchTeamDashboard(trackId, days, includeDemo, enrolledOnly)
      .then(data => { if (!cancelled) { setDashboard(data); setError(""); } })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : "读取团队看板失败"); });
    return () => { cancelled = true; };
  }, [user, trackId, days, includeDemo, enrolledOnly]);

  useEffect(() => {
    if (!dashboard) return;
    queueMicrotask(() => setHeatmap(dashboard.members.flatMap(member => member.services.map(service => ({
      member: `${member.display_name || member.username} · ${member.username}`,
      dimension: service.service_name,
      score: service.score,
      state: service.state,
      questionCount: service.question_count,
      assessedAt: service.assessed_at,
      userId: member.user_id,
    })))));
  }, [dashboard]);

  return (
    <main className="min-h-screen bg-slate-900 text-slate-100 py-10 px-4">
      <div className="sage-content mx-auto max-w-6xl space-y-8">
        {!user ? (
          <p className="text-slate-400 text-center py-12">加载中…</p>
        ) : (
        <>
        <header>
          <div className="flex items-center justify-between flex-wrap gap-4">
            <div>
              <h1 className="sage-page-title text-3xl font-bold mb-1">📊 团队能力看板</h1>
              <p className="sage-page-description text-slate-400">
                {trackId} 方向 · 展示测评证据，不把未测评视为低分
              </p>
            </div>
            <div className="flex gap-2">
              <Link href="/dashboard/knowledge" className="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 rounded text-white text-sm">知识库</Link>
              <Link href="/dashboard/accounts" className="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 rounded text-white text-sm">账号管理</Link>
              <Link href="/" className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-white text-sm">← 返回首页</Link>
            </div>
          </div>
        </header>

        {error && <p role="alert" className="text-rose-300">{error}</p>}
        <div className="flex flex-wrap gap-4 rounded-xl border border-slate-700 bg-slate-800 p-4 text-sm">
          <label>时间范围 <select value={days} onChange={e => setDays(Number(e.target.value) as 0 | 30 | 90)} className="ml-2 rounded bg-slate-950 px-2 py-1"><option value={0}>全部</option><option value={30}>近 30 天</option><option value={90}>近 90 天</option></select></label>
          <label><input type="checkbox" checked={includeDemo} onChange={e => setIncludeDemo(e.target.checked)} className="mr-2" />包含样例账号</label>
          <label><input type="checkbox" checked={enrolledOnly} onChange={e => setEnrolledOnly(e.target.checked)} className="mr-2" />仅看培训名单</label>
          <span className="text-slate-400">默认仅显示启用的正式成员；当前名单 {dashboard?.metrics.enrolled_members ?? 0} 人，可在账号管理中维护。</span>
        </div>
        {!dashboard ? (
          <p className="text-slate-400 text-center py-12">加载中…</p>
        ) : (
          <>
            <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">{enrolledOnly ? "培训名单成员" : "启用成员"}</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {dashboard.metrics.members}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">已测服务 / 全部服务</div>
                <div className="text-2xl font-bold text-emerald-400">
                  {dashboard.metrics.tested_services} / {dashboard.metrics.total_services}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">已参与测评</div>
                <div className="text-2xl font-bold text-amber-400">{dashboard.metrics.assessed_members} / {dashboard.metrics.members}</div>
              </div>
              <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">进行中计划</div>
                <div className="text-2xl font-bold text-emerald-400">{dashboard.metrics.active_plans}</div>
              </div>
            </section>

            <section className="bg-slate-800 rounded-xl p-6 border border-slate-700">
              <h2 className="text-lg font-semibold mb-4">团队测评证据</h2>
              <HeatmapChart data={heatmap} height={420} onMemberClick={openMember} />
              <p className="text-xs text-slate-400 mt-2">
                灰色＝未测；琥珀色＝题量或维度不足的参考分；其他颜色＝证据较充分的本次得分。不同题目和难度的分数不直接求团队均分。点击格子查看成员。
              </p>
            </section>

            <section className="grid gap-5 md:grid-cols-2">
              <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
                <h2 className="text-lg font-semibold mb-4">成员与记录</h2>
                <div className="space-y-2">{dashboard.members.map(member => <button key={member.user_id} onClick={() => openMember(member.user_id)} className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-left text-sm hover:border-emerald-500">{member.display_name || member.username} · 测评 {member.assessment_count} · 工单 {member.ticket_count} · 计划 {member.active_plan_count} →</button>)}</div>
              </div>
              <div className="bg-slate-800 rounded-xl p-6 border border-slate-700">
                <h2 className="text-lg font-semibold mb-4">待跟进</h2>
                <div className="space-y-2">{dashboard.followups.map((item, index) => <button key={`${item.user_id}-${index}`} onClick={() => openMember(item.user_id)} className="w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-left text-sm hover:border-emerald-500">{item.username} · {item.reason} →</button>)}{dashboard.followups.length === 0 && <p className="text-sm text-slate-400">暂无待跟进事项</p>}</div>
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

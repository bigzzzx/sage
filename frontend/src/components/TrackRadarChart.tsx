"use client";

import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import RadarChart from "./RadarChart";
import type { UserServiceScore } from "@/lib/api";

interface Props {
  data: UserServiceScore[];
  height?: number;
}

export default function TrackRadarChart({ data, height = 420 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [hoveredService, setHoveredService] = useState<UserServiceScore | null>(
    null,
  );

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = echarts.init(ref.current);

    const indicators = data.map((s) => ({
      name: `${s.icon || ""} ${s.service_name}${s.is_tested ? "" : " (未测)"}`,
      max: 5,
    }));

    chart.setOption({
      tooltip: {
        trigger: "item",
        formatter: () =>
          data
            .map(
              (s) =>
                `<div style="margin-bottom:4px">${s.icon || ""} ${s.service_name}: <b>${
                  s.is_tested ? `${s.score}/5` : "未测评"
                }</b></div>`,
            )
            .join(""),
      },
      radar: {
        indicator: indicators,
        radius: "65%",
        splitNumber: 5,
        axisName: { color: "#cbd5e1", fontSize: 12 },
        splitLine: { lineStyle: { color: "rgba(148,163,184,0.3)" } },
        splitArea: {
          areaStyle: {
            color: ["rgba(16,185,129,0.04)", "rgba(16,185,129,0.08)"],
          },
        },
        axisLine: { lineStyle: { color: "rgba(148,163,184,0.4)" } },
      },
      series: [
        {
          type: "radar",
          data: [
            {
              value: data.map((s) => s.score),
              name: "能力得分",
              areaStyle: { color: "rgba(16,185,129,0.35)" },
              lineStyle: { color: "#10b981", width: 2 },
              itemStyle: { color: "#10b981" },
              symbolSize: 6,
            },
          ],
        },
      ],
    });

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [data]);

  if (data.length === 0) {
    return <div className="text-slate-400 text-center py-12">暂无数据</div>;
  }

  const capRadarData = hoveredService
    ? hoveredService.capabilities.map((c) => ({
        dimension_id: c.capability_id,
        dimension_name: c.capability_name,
        score: c.score,
      }))
    : [];

  return (
    <div>
      <div ref={ref} style={{ width: "100%", height }} />

      {/* Service 标签栏：hover 弹出 capability 雷达 */}
      <div className="flex flex-wrap gap-2 justify-center mt-2">
        {data.map((s) => {
          const hasCaps = s.is_tested && s.capabilities && s.capabilities.length > 0;
          return (
            <div
              key={s.service_id}
              className="relative"
              onMouseEnter={() => hasCaps && setHoveredService(s)}
              onMouseLeave={() => setHoveredService(null)}
            >
              <span
                className={`inline-block text-xs px-2.5 py-1 rounded-full border transition-colors cursor-default ${
                  hasCaps
                    ? "border-emerald-600/50 text-emerald-300 hover:bg-emerald-600/20"
                    : "border-slate-700 text-slate-500"
                }`}
              >
                {s.icon} {s.service_name}
                {s.is_tested ? ` ${s.score}/5` : " 未测"}
              </span>

              {/* Hover 浮层 */}
              {hoveredService?.service_id === s.service_id && capRadarData.length > 0 && (
                <div
                  className="absolute z-50 bottom-full mb-2 left-1/2 -translate-x-1/2 bg-slate-900 border border-emerald-700/50 rounded-xl shadow-2xl p-4"
                  style={{ width: 340 }}
                  onMouseEnter={() => setHoveredService(s)}
                  onMouseLeave={() => setHoveredService(null)}
                >
                  <div className="text-sm font-semibold text-emerald-400 mb-1">
                    {s.icon} {s.service_name} 能力详情
                  </div>
                  <div className="text-[10px] text-slate-500 mb-1">
                    综合 {s.score}/5 · {s.capabilities.length} 个能力点
                  </div>
                  {capRadarData.length >= 3 ? (
                    <RadarChart data={capRadarData} height={220} />
                  ) : (
                    <div className="space-y-2 mt-2">
                      {capRadarData.map((c) => {
                        const pct = (c.score / 5) * 100;
                        const color =
                          c.score < 3
                            ? "bg-rose-500"
                            : c.score < 4
                              ? "bg-amber-500"
                              : "bg-emerald-500";
                        return (
                          <div key={c.dimension_id}>
                            <div className="flex justify-between text-xs mb-0.5">
                              <span className="text-slate-200">
                                {c.dimension_name}
                              </span>
                              <span className="text-slate-400">
                                {c.score}/5
                              </span>
                            </div>
                            <div className="h-2 bg-slate-800 rounded">
                              <div
                                className={`h-full rounded ${color}`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-slate-600 text-center mt-1">
        💡 鼠标悬停在已测服务标签上可查看各能力点雷达
      </p>
    </div>
  );
}

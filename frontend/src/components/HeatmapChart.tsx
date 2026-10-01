"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

const escapeHtml = (value: string) => value.replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char] || char);

export interface HeatmapPoint {
  member: string;
  dimension: string;
  score: number | null;
  state: "untested" | "reference" | "observed";
  questionCount?: number;
  assessedAt?: string | null;
  userId?: string;
}

interface Props {
  data: HeatmapPoint[];
  height?: number;
  onMemberClick?: (userId: string) => void;
}

export default function HeatmapChart({ data, height = 360, onMemberClick }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = echarts.init(ref.current);

    const members = Array.from(new Set(data.map((d) => d.member)));
    const dimensions = Array.from(new Set(data.map((d) => d.dimension)));

    const seriesData = (state: HeatmapPoint["state"]) => data.map((d, index) => d.state === state ? {
      value: [members.indexOf(d.member), dimensions.indexOf(d.dimension), d.score ?? -1],
      pointIndex: index,
      label: { formatter: state === "untested" ? "—" : state === "reference" ? "参考" : String(d.score) },
    } : null).filter(Boolean);

    chart.setOption({
      tooltip: {
        position: "top",
        formatter: (p: { data: { pointIndex: number }; value: [number, number, number] }) => {
          const point = data[p.data.pointIndex];
          const m = members[p.value[0]];
          const dim = dimensions[p.value[1]];
          const detail = point.state === "untested" ? "未测评" :
            `${point.score}/5 · ${point.state === "reference" ? "题量或维度覆盖不足，仅供参考" : "证据较充分"}<br/>有效题数 ${point.questionCount ?? 0}<br/>${point.assessedAt ? new Date(point.assessedAt).toLocaleDateString("zh-CN") : ""}`;
          return `${escapeHtml(m)}<br/>${escapeHtml(dim)}: <b>${detail}</b>`;
        },
      },
      grid: { left: 140, right: 20, top: 30, bottom: 80 },
      xAxis: {
        type: "category",
        data: members,
        axisLabel: { color: "#cbd5e1", rotate: 30 },
        splitArea: { show: true },
      },
      yAxis: {
        type: "category",
        data: dimensions,
        axisLabel: {
          color: "#cbd5e1",
          formatter: (v: string) => (v.length > 14 ? v.slice(0, 12) + "…" : v),
        },
        splitArea: { show: true },
      },
      visualMap: [
        {
          min: 0, max: 5, seriesIndex: 0, calculable: false,
          orient: "horizontal", left: "center", bottom: 0,
          textStyle: { color: "#cbd5e1" },
          inRange: { color: ["#ef4444", "#f59e0b", "#10b981"] },
        },
        { min: 0, max: 5, seriesIndex: 1, show: false,
          inRange: { color: ["#b45309", "#b45309"] } },
        { min: -1, max: 5, seriesIndex: 2, show: false,
          inRange: { color: ["#475569", "#475569"] } },
      ],
      series: [
        {
          name: "能力分",
          type: "heatmap",
          data: seriesData("observed"),
          label: { show: true, color: "#0f172a", fontSize: 12 },
          emphasis: {
            itemStyle: {
              shadowBlur: 8,
              shadowColor: "rgba(0,0,0,0.5)",
            },
          },
        },
        { name: "参考", type: "heatmap", data: seriesData("reference"),
          itemStyle: { color: "#b45309" }, label: { show: true, color: "#fff", fontSize: 12 } },
        { name: "未测", type: "heatmap", data: seriesData("untested"),
          itemStyle: { color: "#475569" }, label: { show: true, color: "#fff", fontSize: 12 } },
      ],
    });

    chart.on("click", event => {
      const plotted = event.data as { pointIndex?: number } | undefined;
      const point = plotted?.pointIndex === undefined ? undefined : data[plotted.pointIndex];
      if (point?.userId) onMemberClick?.(point.userId);
    });

    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [data, onMemberClick]);

  if (data.length === 0) {
    return (
      <div className="text-slate-400 text-center py-12">暂无团队数据</div>
    );
  }
  return <div ref={ref} style={{ width: "100%", height }} />;
}

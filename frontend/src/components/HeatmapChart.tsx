"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";

export interface HeatmapPoint {
  member: string;
  dimension: string;
  score: number; // 0~5
}

interface Props {
  data: HeatmapPoint[];
  height?: number;
}

export default function HeatmapChart({ data, height = 360 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = echarts.init(ref.current);

    const members = Array.from(new Set(data.map((d) => d.member)));
    const dimensions = Array.from(new Set(data.map((d) => d.dimension)));

    const seriesData = data.map((d) => [
      members.indexOf(d.member),
      dimensions.indexOf(d.dimension),
      d.score,
    ]);

    chart.setOption({
      tooltip: {
        position: "top",
        formatter: (p: { value: [number, number, number] }) => {
          const m = members[p.value[0]];
          const dim = dimensions[p.value[1]];
          return `${m}<br/>${dim}: <b>${p.value[2]}/5</b>`;
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
      visualMap: {
        min: 0,
        max: 5,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        textStyle: { color: "#cbd5e1" },
        inRange: {
          color: ["#ef4444", "#f59e0b", "#10b981"],
        },
      },
      series: [
        {
          name: "能力分",
          type: "heatmap",
          data: seriesData,
          label: { show: true, color: "#0f172a", fontSize: 12 },
          emphasis: {
            itemStyle: {
              shadowBlur: 8,
              shadowColor: "rgba(0,0,0,0.5)",
            },
          },
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
    return (
      <div className="text-slate-400 text-center py-12">暂无团队数据</div>
    );
  }
  return <div ref={ref} style={{ width: "100%", height }} />;
}

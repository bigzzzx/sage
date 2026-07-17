"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { RadarItem } from "@/lib/api";

interface Props {
  data: RadarItem[];
  height?: number;
}

export default function RadarChart({ data, height = 380 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;

    const chart = echarts.init(ref.current);

    // 维度名称太长会重叠，给点截断
    const indicators = data.map((d) => ({
      name:
        d.dimension_name.length > 14
          ? d.dimension_name.slice(0, 12) + "…"
          : d.dimension_name,
      max: 5,
    }));

    chart.setOption({
      tooltip: {
        trigger: "item",
        formatter: () => {
          return data
            .map(
              (d) =>
                `<div style="margin-bottom:4px">${d.dimension_name}: <b>${d.score}/5</b></div>`,
            )
            .join("");
        },
      },
      radar: {
        indicator: indicators,
        radius: "65%",
        splitNumber: 5,
        axisName: {
          color: "#cbd5e1",
          fontSize: 12,
        },
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
              value: data.map((d) => d.score),
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
    return (
      <div className="text-slate-400 text-center py-12">暂无能力数据</div>
    );
  }

  return <div ref={ref} style={{ width: "100%", height }} />;
}

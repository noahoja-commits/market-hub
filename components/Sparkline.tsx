"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";

type Point = { date: string; value: number };
type Format = "currency" | "percent" | "integer" | "decimal";

function formatValue(v: number, format: Format): string {
  switch (format) {
    case "currency":
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(v);
    case "percent":
      return `${v.toFixed(2)}%`;
    case "integer":
      return v.toFixed(0);
    case "decimal":
      return v.toFixed(2);
  }
}

export function Sparkline({
  data,
  color = "#0ea5e9",
  height = 60,
  format = "currency",
}: {
  data: Point[];
  color?: string;
  height?: number;
  format?: Format;
}) {
  if (!data.length) {
    return (
      <div
        className="text-xs text-zinc-400 italic flex items-center"
        style={{ height }}
      >
        no data
      </div>
    );
  }
  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.1 || 1;
  const gradId = `grad-${color.replace("#", "")}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <YAxis domain={[min - pad, max + pad]} hide />
        <Tooltip
          contentStyle={{
            background: "rgba(0,0,0,0.85)",
            border: "none",
            borderRadius: 6,
            fontSize: 12,
            color: "#fff",
            padding: "4px 8px",
          }}
          labelFormatter={(d) =>
            new Date(d).toLocaleDateString("en-US", {
              month: "short",
              year: "numeric",
            })
          }
          formatter={(v) => {
            const n = typeof v === "number" ? v : Number(v);
            return [formatValue(n, format), ""];
          }}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={1.75}
          fill={`url(#${gradId})`}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

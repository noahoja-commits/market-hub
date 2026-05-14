"use client";

import {
  CartesianGrid,
  Line,
  LineChart as ReLineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Point = { date: string; value: number };
type Format = "currency" | "percent" | "integer" | "decimal" | "decimal1";

function fmt(v: number, format: Format): string {
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
    case "decimal1":
      return v.toFixed(1);
  }
}

function tickFmt(v: number, format: Format): string {
  switch (format) {
    case "currency":
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(v);
    case "percent":
      return `${v.toFixed(1)}%`;
    case "integer":
      return v.toFixed(0);
    case "decimal":
    case "decimal1":
      return v.toFixed(1);
  }
}

export function LineChart({
  data,
  color = "#0ea5e9",
  height = 220,
  format = "integer",
}: {
  data: Point[];
  color?: string;
  height?: number;
  format?: Format;
}) {
  if (!data.length) {
    return (
      <div
        className="text-sm text-zinc-400 italic flex items-center justify-center"
        style={{ height }}
      >
        no data
      </div>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ReLineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
        <XAxis
          dataKey="date"
          stroke="#71717a"
          fontSize={11}
          tickFormatter={(d) =>
            new Date(d).toLocaleDateString("en-US", {
              month: "short",
              year: "2-digit",
            })
          }
          minTickGap={40}
        />
        <YAxis
          stroke="#71717a"
          fontSize={11}
          tickFormatter={(v) => tickFmt(Number(v), format)}
          width={60}
        />
        <Tooltip
          contentStyle={{
            background: "rgba(0,0,0,0.9)",
            border: "1px solid #3f3f46",
            borderRadius: 6,
            fontSize: 12,
            color: "#fff",
          }}
          labelFormatter={(d) =>
            new Date(d).toLocaleDateString("en-US", {
              month: "short",
              year: "numeric",
            })
          }
          formatter={(v) => {
            const n = typeof v === "number" ? v : Number(v);
            return [fmt(n, format), ""];
          }}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </ReLineChart>
    </ResponsiveContainer>
  );
}

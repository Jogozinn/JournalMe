"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { dateTime, money } from "@/lib/api";

export default function EquityChart({
  points,
}: {
  points: { at: string; value: string }[];
}) {
  const data = points.map((point) => ({ ...point, value: Number(point.value) }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data}>
        <defs>
          <linearGradient id="equity" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5fc99a" stopOpacity={0.28} />
            <stop offset="100%" stopColor="#5fc99a" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="rgba(202,221,208,.07)" vertical={false} />
        <XAxis dataKey="at" hide />
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip
          contentStyle={{
            background: "#151a16",
            border: "1px solid rgba(202,221,208,.15)",
            borderRadius: 10,
          }}
          formatter={(value) => money(String(value))}
          labelFormatter={(label) => dateTime(String(label))}
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke="#5fc99a"
          strokeWidth={2}
          fill="url(#equity)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

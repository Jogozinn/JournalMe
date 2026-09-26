"use client";

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { money } from "@/lib/api";

type Row = { label: string; net_pnl: string };

export default function PerformanceBarChart({ rows }: { rows: Row[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows.map((row) => ({ ...row, net_pnl: Number(row.net_pnl) }))}>
        <CartesianGrid stroke="rgba(202,221,208,.07)" vertical={false} />
        <XAxis dataKey="label" stroke="#7f8a82" tickLine={false} axisLine={false} />
        <YAxis hide />
        <ReferenceLine y={0} stroke="rgba(202,221,208,.35)" />
        <Tooltip
          contentStyle={{
            background: "#151a16",
            border: "1px solid rgba(202,221,208,.15)",
            borderRadius: 10,
          }}
          formatter={(value) => money(String(value))}
        />
        <Bar dataKey="net_pnl" radius={[5, 5, 0, 0]} isAnimationActive={false}>
          {rows.map((row) => (
            <Cell
              key={row.label}
              fill={Number(row.net_pnl) < 0 ? "#ef806f" : "#5fc99a"}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

"use client";

import * as React from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Api } from "@/data/fixtures/scenarios";
import { formatTime } from "@/lib/utils";

type Point = Api["MetricHistoryPoint"];

export function MetricChart({ points, baseline, mode = "rate", compact = false }: { points: Point[]; baseline: number; mode?: "rate" | "latency" | "approval"; compact?: boolean }): React.JSX.Element {
  const data = points.map((point) => ({
    ...point,
    displayValue: point.value === null ? null : mode === "rate" || mode === "approval" ? point.value * 100 : point.value
  }));
  const displayBaseline = mode === "rate" || mode === "approval" ? baseline * 100 : baseline;
  const unit = mode === "latency" ? "ms" : "%";
  const first = points[0];
  const last = points.at(-1);
  const summary = first && last
    ? `From ${formatTime(first.at)} to ${formatTime(last.at)}, the displayed metric changed from ${data[0]?.displayValue?.toFixed(2) ?? "unavailable"}${unit} to ${data.at(-1)?.displayValue?.toFixed(2) ?? "unavailable"}${unit}.`
    : "No metric samples are available for this window.";

  return (
    <figure aria-label="Metric history chart" className="w-full">
      <div className={compact ? "h-56" : "h-[19rem]"}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 14, right: 12, bottom: 0, left: -8 }}>
            <defs><linearGradient id={`metric-fill-${mode}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity={0.28} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0.02} /></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 5" />
            <XAxis dataKey="at" tickFormatter={formatTime} axisLine={false} tickLine={false} minTickGap={36} tick={{ fill: "var(--ink-muted)", fontSize: 11 }} />
            <YAxis tickFormatter={(value: number) => `${value.toFixed(mode === "latency" ? 0 : 1)}${unit}`} axisLine={false} tickLine={false} tick={{ fill: "var(--ink-muted)", fontSize: 11 }} width={52} />
            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 12, color: "var(--ink)", fontSize: 12 }} labelFormatter={(label) => formatTime(String(label))} formatter={(value) => [`${Number(value).toFixed(mode === "latency" ? 0 : 2)}${unit}`, "Current"]} />
            <ReferenceLine y={displayBaseline} stroke="var(--ink-muted)" strokeDasharray="5 5" label={{ value: "Baseline", fill: "var(--ink-muted)", fontSize: 10, position: "insideTopRight" }} />
            <Area type="monotone" dataKey="displayValue" stroke="var(--accent)" strokeWidth={2.5} fill={`url(#metric-fill-${mode})`} isAnimationActive={false} activeDot={{ r: 4, fill: "var(--surface)", stroke: "var(--accent)", strokeWidth: 2 }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 text-xs leading-5 text-[var(--ink-muted)]">{summary}</figcaption>
      <details className="mt-2 text-xs text-[var(--ink-soft)]"><summary className="cursor-pointer font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]">Accessible data summary</summary><table className="mt-2 w-full max-w-lg"><thead><tr className="text-left"><th className="py-1">Time</th><th>Value</th></tr></thead><tbody>{data.filter((_, index) => index % 4 === 0 || index === data.length - 1).map((point) => <tr key={point.at}><td className="py-1">{formatTime(point.at)}</td><td>{point.displayValue?.toFixed(mode === "latency" ? 0 : 2) ?? "Unavailable"}{unit}</td></tr>)}</tbody></table></details>
    </figure>
  );
}

import { useState } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  LineChart,
  Line,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
  ReferenceLine,
} from "recharts";
import { fmtValue, signed, compact, fmt1 } from "../lib/format";
import BlockedCard from "./BlockedCard";

const CATEGORY_COLORS = {
  Electronics: "#4F8EF7",
  Apparel: "#A78BFA",
  "Home & Kitchen": "#F5B04C",
  Grocery: "#34D399",
  "Sports & Outdoors": "#F97066",
};

const AXIS_TICK = { fontSize: 10, fill: "#5D6F8F" };
const TOOLTIP_STYLE = {
  backgroundColor: "#0E1627",
  border: "1px solid #1D2A45",
  borderRadius: 8,
  fontSize: 12,
};

// higherIsBetter: Revenue/Units/GM% go up = good; churn goes up = bad.
function DeltaChip({ value, unit, higherIsBetter = true }) {
  if (value == null) return null;
  const up = value > 0;
  const good = higherIsBetter ? up : !up;
  return (
    <span
      className={
        "num rounded px-1.5 py-0.5 text-[11px] " +
        (good ? "bg-conf-high/10 text-conf-high" : "bg-conf-low/10 text-conf-low")
      }
    >
      {up ? "▲" : "▼"} {signed(value, unit)}
    </span>
  );
}

function DailyChart({ kpi, points, markers, byCategory, unit }) {
  const [mode, setMode] = useState("total");
  const band = (markers || []).find((m) => m.type === "anomaly_band");
  const launch = (markers || []).find((m) => m.type === "launch");

  return (
    <div>
      {byCategory && (
        <div className="mb-2 flex gap-1">
          {["total", "category"].map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={
                "rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
                (mode === m
                  ? "bg-accent-soft text-accent"
                  : "text-mist-dim hover:text-mist")
              }
            >
              {m === "total" ? "Total" : "By category"}
            </button>
          ))}
        </div>
      )}
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          {mode === "category" && byCategory ? (
            <LineChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="#141F36" vertical={false} />
              <XAxis dataKey="date" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "#1D2A45" }} minTickGap={32} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={compact} width={52} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#8FA3C0" }} formatter={(v) => fmtValue(v, unit)} />
              {band && <ReferenceArea x1={band.start} x2={band.end} fill="#F97066" fillOpacity={0.07} />}
              {launch && (
                <ReferenceLine x={launch.date} stroke="#34D399" strokeDasharray="4 4"
                  label={{ value: "launch", position: "insideTopRight", fill: "#34D399", fontSize: 10 }} />
              )}
              {Object.entries(byCategory).map(([cat, series]) => (
                <Line key={cat} type="monotone" data={series} dataKey="value"
                  name={cat} stroke={CATEGORY_COLORS[cat] || "#8FA3C0"}
                  dot={false} strokeWidth={1.4} connectNulls />
              ))}
            </LineChart>
          ) : (
            <AreaChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
              <defs>
                <linearGradient id={`grad-${kpi.replace(/[^a-zA-Z0-9]/g, "")}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4F8EF7" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="#4F8EF7" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#141F36" vertical={false} />
              <XAxis dataKey="date" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "#1D2A45" }} minTickGap={32} />
              <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={compact} width={52} />
              <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#8FA3C0" }} formatter={(v) => fmtValue(v, unit)} />
              {band && <ReferenceArea x1={band.start} x2={band.end} fill="#F97066" fillOpacity={0.09} />}
              {launch && (
                <ReferenceLine x={launch.date} stroke="#34D399" strokeDasharray="4 4"
                  label={{ value: "launch", position: "insideTopRight", fill: "#34D399", fontSize: 10 }} />
              )}
              <Area type="monotone" dataKey="value" stroke="#4F8EF7" strokeWidth={1.6}
                fill={`url(#grad-${kpi.replace(/[^a-zA-Z0-9]/g, "")})`} />
            </AreaChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function MonthlyChart({ kpi, points, completeness, unit }) {
  return (
    <div>
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} margin={{ top: 12, right: 4, bottom: 0, left: -18 }} barCategoryGap="32%">
            <CartesianGrid stroke="#141F36" vertical={false} />
            <XAxis dataKey="period" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "#1D2A45" }} />
            <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} tickFormatter={compact} width={44} />
            <Tooltip contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "#8FA3C0" }} formatter={(v) => fmtValue(v, unit)} cursor={{ fill: "#16233C", opacity: 0.5 }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {points.map((p) => {
                const comp = completeness ? completeness[p.period] : 1;
                return (
                  <Cell key={p.period} fill={comp < 0.9 ? "#F97066" : "#4F8EF7"} />
                );
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-mist-dim">
        {points.map((p) => {
          const comp = completeness ? completeness[p.period] : 1;
          return (
            <span key={p.period} className="flex items-center gap-1">
              <span className="inline-block h-1.5 w-1.5 rounded-sm" style={{ background: comp < 0.9 ? "#F97066" : "#4F8EF7" }} />
              {p.period} · {fmt1(p.value)}%
              {comp < 0.9 && <span className="text-conf-low">· {fmt1(comp * 100)}% complete</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export default function KpiTrendCard({ kpi, series, blocked }) {
  if (!series) return null;

  if (blocked) {
    return (
      <div className="rounded-xl border border-line bg-ink-900 p-4">
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-mist-bright">{kpi}</h3>
          <span className="text-[10px] uppercase tracking-wider text-mist-dim">{series.grain}</span>
        </div>
        <BlockedCard blocked={blocked} />
      </div>
    );
  }

  const points = series.points || [];
  const last = points[points.length - 1];
  const prev = points[points.length - 2];
  const delta = last && prev ? last.value - prev.value : null;
  const lastKey = series.grain === "monthly" ? "period" : "date";
  const lastLabel = last ? last[lastKey] : "";
  const higherIsBetter = kpi !== "Customer Churn Rate";

  return (
    <div className="rounded-xl border border-line bg-ink-900 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-mist-bright">{kpi}</h3>
        <span className="text-[10px] uppercase tracking-wider text-mist-dim">
          {series.grain} grain
        </span>
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="num text-2xl font-semibold text-slate-100">
          {last ? fmtValue(last.value, series.unit) : "—"}
        </span>
        <DeltaChip value={delta} unit={series.unit} higherIsBetter={higherIsBetter} />
        {lastLabel && <span className="num ml-auto text-[10px] text-mist-dim">{lastLabel}</span>}
      </div>
      <div className="mt-3">
        {series.grain === "monthly" ? (
          <MonthlyChart kpi={kpi} points={points} completeness={series.completeness} unit={series.unit} />
        ) : (
          <DailyChart
            kpi={kpi}
            points={points}
            markers={series.markers}
            byCategory={series.by_category}
            unit={series.unit}
          />
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-mist-dim">
        {(series.markers || []).map((m) =>
          m.type === "anomaly_band" ? (
            <span key="band" className="flex items-center gap-1">
              <span className="inline-block h-1.5 w-3 rounded-sm bg-conf-low/40" />
              {m.label}
            </span>
          ) : (
            <span key="launch" className="flex items-center gap-1">
              <span className="inline-block h-0 w-3 border-t border-dashed border-conf-high" />
              {m.label}
            </span>
          )
        )}
      </div>
    </div>
  );
}

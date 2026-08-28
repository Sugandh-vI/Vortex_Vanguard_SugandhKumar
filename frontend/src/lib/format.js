// Formatting helpers — unit-aware, consistent with the contract's `unit`
// field (USD / units / percent / percentage_points).

export function fmt1(v) {
  return (Math.round(v * 10) / 10).toFixed(1);
}

export function money(v, digits = 2) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(v);
}

export function fmtValue(v, unit) {
  if (v == null || Number.isNaN(v)) return "—";
  switch (unit) {
    case "USD":
      return money(v);
    case "units":
      return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
    case "percent":
      return `${fmt1(v)}%`;
    case "percentage_points":
      return `${fmt1(v)} pp`;
    default:
      return String(v);
  }
}

export function signed(v, unit) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v > 0 ? "+" : ""}${fmtValue(v, unit)}`;
}

export function fmtMs(v) {
  if (v == null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(2)}s` : `${Math.round(v)}ms`;
}

export function fmtTokens(v) {
  return new Intl.NumberFormat("en-US").format(v ?? 0);
}

// Compact axis labels: 57,146 -> 57.1k
export function compact(v) {
  if (v == null) return "";
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) {
    return `${(v / 1_000).toFixed(Math.abs(v) >= 10_000 ? 0 : 1)}k`;
  }
  return String(Math.round(v * 10) / 10);
}

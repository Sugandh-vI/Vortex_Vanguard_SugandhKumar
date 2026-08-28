import { useState } from "react";

const SCENARIOS = [
  {
    title: "Week-7 multi-factor dip — 2024-05-13",
    steps: [
      "Red band across the Revenue / Units Sold / Gross Margin % cards marks the scripted week-7 event.",
      "Rank-1 insight: Gross Margin % @ 2024-05-13, z −16.1 — the engine decomposes it to unit_price (attribution 1.0, known cause).",
      "CFO gets a quantified “Pricing & Margin Recovery” recommendation; the narration is clearly labeled [MOCK] or live.",
    ],
  },
  {
    title: "Sports & Outdoors launch — sparse history",
    steps: [
      "Green dashed launch marker on 2024-06-19 on the daily KPI cards (category launched mid-window).",
      "Bottom of the feed: three Sports & Outdoors ABSTAIN cards — 11/21 days of history, so the engine refuses to narrate business causes for the new category.",
    ],
  },
  {
    title: "June churn at 70% completeness",
    steps: [
      "The June bar on Customer Churn Rate is red: 70.2% of expected customers — below the 90% threshold.",
      "The churn insight ABSTAINS on business actions and instead issues a “Data Quality & Pipeline” action — the engine’s honesty, on display.",
    ],
  },
  {
    title: "Feedback weighting (Phase 9, live)",
    steps: [
      "Switch to Category Manager → on “Revenue | 2024-05-13” click 👎 twice → a ×0.5 factor chip appears, 72.7 → 36.4, and the insight sinks in the feed.",
      "Switch to CFO → click 👍 once → ×1.333, 72.7 → 96.9. The factor is per (KPI × confidence level × persona) — a trust label, never evidence: the confidence badge itself never changes.",
      "Votes persist in backend/data/raw/feedback.db (delete the file to reset the demo).",
    ],
  },
];

export default function DemoScenarios({ defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-xl border border-line bg-ink-900">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        <h2 className="text-sm font-semibold text-mist-bright">Demo guide</h2>
        <span className="rounded border border-accent/30 bg-accent-soft/50 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-accent">
          4 scripted scenarios
        </span>
        <span className="ml-auto text-[11px] text-mist-dim">{open ? "hide ▴" : "show ▾"}</span>
      </button>
      {open && (
        <div className="grid grid-cols-1 gap-3 border-t border-line/60 p-4 md:grid-cols-2">
          {SCENARIOS.map((s, i) => (
            <div key={s.title} className="rounded-lg border border-line bg-ink-850 p-3">
              <p className="text-[12px] font-medium text-mist-bright">
                <span className="num mr-2 text-accent">{i + 1}</span>
                {s.title}
              </p>
              <ul className="mt-2 space-y-1.5">
                {s.steps.map((step, j) => (
                  <li key={j} className="flex gap-2 text-[11px] leading-relaxed text-mist">
                    <span className="mt-1.5 inline-block h-1 w-1 shrink-0 rounded-full bg-mist-dim" />
                    {step}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

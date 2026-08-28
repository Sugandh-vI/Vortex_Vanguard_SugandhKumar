import { useState } from "react";
import InsightCard from "./InsightCard";
import BlockedCard from "./BlockedCard";

const KPI_LEVEL_UNITS = {
  Revenue: "USD",
  "Units Sold": "units",
  "Gross Margin %": "percent",
  "Customer Churn Rate": "percent",
};

const KPI_DELTA_UNITS = {
  Revenue: "USD",
  "Units Sold": "units",
  "Gross Margin %": "percentage_points",
  "Customer Churn Rate": "percentage_points",
};

const VISIBLE_BY_DEFAULT = 6;

export default function InsightFeed({
  insights = [],
  blocked = [],
  persona,
  lastVotes = {},
  onVote,
  voting,
  voteError,
}) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? insights : insights.slice(0, VISIBLE_BY_DEFAULT);

  return (
    <div className="rounded-xl border border-line bg-ink-900 p-4">
      <div className="mb-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-mist-bright">Insight feed</h2>
          <span className="num text-[11px] text-mist-dim">
            {insights.length} insights · {persona}
          </span>
        </div>
        <p className="mt-0.5 text-[10px] text-mist-dim">
          ranked by confidence × feedback factor · abstains last
        </p>
      </div>
      {voteError && (
        <div className="mb-2 rounded-md border border-blocked/30 bg-blocked/[0.06] px-3 py-1.5 text-[11px] text-blocked">
          {voteError}
        </div>
      )}

      {blocked.length > 0 && (
        <div className="mb-3 space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-mist-dim">
            Blocked by access control
          </p>
          {blocked.map((b) => (
            <BlockedCard key={b.kpi_name} blocked={b} />
          ))}
        </div>
      )}

      <div className="scroll-slim max-h-[72vh] space-y-3 overflow-y-auto pr-1">
        {visible.map((i) => (
          <InsightCard
            key={i.insight_id}
            insight={i}
            unit={KPI_LEVEL_UNITS[i.kpi_name] || "percent"}
            deltaUnit={KPI_DELTA_UNITS[i.kpi_name]}
            lastVote={lastVotes[i.insight_id]}
            onVote={onVote}
            voting={voting}
          />
        ))}
      </div>

      {insights.length > VISIBLE_BY_DEFAULT && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="mt-3 w-full rounded-lg border border-line bg-ink-850 py-2 text-xs text-mist hover:border-accent/40 hover:text-mist-bright"
        >
          {showAll ? "Show top 6" : `Show all ${insights.length} insights`}
        </button>
      )}
    </div>
  );
}

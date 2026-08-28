import { useState } from "react";
import ConfidenceBadge from "./ConfidenceBadge";
import { fmtValue, signed, fmt1 } from "../lib/format";

const WEIGHT_STYLES = {
  1.0: { label: "known cause", cls: "bg-conf-high/10 text-conf-high border-conf-high/30" },
  0.5: { label: "measured", cls: "bg-conf-medium/10 text-conf-medium border-conf-medium/30" },
  0.0: { label: "context", cls: "bg-ink-700 text-mist-dim border-line" },
};

function weightStyle(w) {
  if (w == null) return WEIGHT_STYLES[0.0];
  const key = Object.keys(WEIGHT_STYLES).find((k) => Math.abs(Number(k) - w) < 0.01);
  return WEIGHT_STYLES[key] || WEIGHT_STYLES[0.0];
}

function ExplainedBar({ label, pct, color }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-[10px]">
        <span className="text-mist-dim">{label}</span>
        <span className="num text-mist">{pct == null ? "—" : `${pct}%`}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.min(100, Math.max(0, pct ?? 0))}%`, background: color }}
        />
      </div>
    </div>
  );
}

function DriverRow({ d, unit }) {
  const w = weightStyle(d.attribution_weight);
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="w-44 shrink-0 truncate font-mono text-[11px] text-mist-bright" title={d.driver_name}>
        {d.driver_name}
      </span>
      <span className="num w-28 shrink-0 text-right text-[11px] text-mist">
        {signed(d.contribution_value, unit)}
      </span>
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full bg-accent/70"
          style={{ width: `${Math.min(100, Math.abs(d.contribution_pct ?? 0))}%` }}
        />
      </div>
      <span className="num w-11 shrink-0 text-right text-[10px] text-mist-dim">
        {fmt1(Math.abs(d.contribution_pct ?? 0))}%
      </span>
      <span className={"w-20 shrink-0 rounded border px-1.5 py-0.5 text-center text-[9px] " + w.cls}>
        {w.label}
        {d.attribution_weight != null && ` ${d.attribution_weight}`}
      </span>
    </div>
  );
}

function ThumbIcon({ up }) {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {up ? (
        <path d="M7 10v11M2 13v6a2 2 0 0 0 2 2h13.5a1.5 1.5 0 0 0 1.4-1l2-7a1.5 1.5 0 0 0-1.45-2H14l1-4.34A2 2 0 0 0 13.1 3L7 10" />
      ) : (
        <path d="M17 14V3M22 11V5a2 2 0 0 0-2-2H6.5a1.5 1.5 0 0 0-1.4 1l-2 7a1.5 1.5 0 0 0 1.45 2H10l-1 4.34A2 2 0 0 0 9.9 21L17 14" />
      )}
    </svg>
  );
}

function VoteButtons({ insight, lastVote, onVote, voting }) {
  const fb = insight.feedback;
  if (!fb) return null;
  const abstain = fb.excluded_from_factor;
  const base = "flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors disabled:opacity-50";
  return (
    <div className="flex items-center gap-1 rounded-md border border-line bg-ink-850 p-0.5">
      <button
        onClick={() => onVote && onVote("up")}
        disabled={voting}
        title={abstain
          ? "Recorded for calibration — abstain insights are excluded from ranking factors"
          : "This insight was useful for me"}
        className={base + (lastVote === "up" ? " bg-conf-high/15 text-conf-high" : " text-mist-dim hover:text-mist-bright")}
      >
        <ThumbIcon up /> <span className="num">{fb.up}</span>
      </button>
      <button
        onClick={() => onVote && onVote("down")}
        disabled={voting}
        title={abstain
          ? "Recorded for calibration — abstain insights are excluded from ranking factors"
          : "This insight was not useful for me"}
        className={base + (lastVote === "down" ? " bg-conf-low/15 text-conf-low" : " text-mist-dim hover:text-mist-bright")}
      >
        <ThumbIcon up={false} /> <span className="num">{fb.down}</span>
      </button>
    </div>
  );
}

function Recommendation({ rec, unit }) {
  const impact = rec.expected_impact;
  const hasImpact =
    impact && impact.value_min != null && impact.value_max != null &&
    !(impact.value_min === 0 && impact.value_max === 0);
  const impactLabel = hasImpact
    ? `${fmtValue(impact.value_min, impact.unit)}–${fmtValue(impact.value_max, impact.unit)}`
    : null;
  return (
    <div className="rounded-lg border border-line bg-ink-850 p-2.5">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-accent">{rec.lever}</span>
        <span className="text-[10px] text-mist-dim">· {rec.owner}</span>
        {rec.actionable ? (
          <span className="ml-auto rounded border border-conf-high/30 bg-conf-high/10 px-1.5 py-0.5 text-[9px] text-conf-high">
            actionable
          </span>
        ) : (
          <span className="ml-auto rounded border border-line bg-ink-700 px-1.5 py-0.5 text-[9px] text-mist-dim">
            not actionable
          </span>
        )}
      </div>
      {rec.actions && rec.actions.length > 0 && (
        <p className="mt-1 text-[11px] leading-relaxed text-mist">{rec.actions[0]}</p>
      )}
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {impactLabel && (
          <span className="num rounded bg-accent-soft/60 px-1.5 py-0.5 text-[10px] text-accent">
            impact {impactLabel}
          </span>
        )}
        {impact?.note && (
          <span className="text-[10px] italic text-mist-dim">{impact.note}</span>
        )}
        {rec.monitoring_plan && (
          <span className="text-[10px] text-mist-dim">monitor: {rec.monitoring_plan}</span>
        )}
      </div>
    </div>
  );
}

export default function InsightCard({ insight, unit, deltaUnit, lastVote, onVote, voting }) {
  const [showAllNarrative, setShowAllNarrative] = useState(false);
  const [showAllRecs, setShowAllRecs] = useState(false);
  const c = insight.confidence;
  const a = insight.anomaly;
  const n = insight.narrative;
  const abstain = c.status === "abstain";
  const recs = insight.recommendations || [];
  const visibleRecs = showAllRecs ? recs : recs.slice(0, 3);

  return (
    <article className="rounded-xl border border-line bg-ink-900 p-4">
      {/* header */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="num rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-mist-dim">
          #{insight.rank}
        </span>
        <h4 className="text-sm font-semibold text-slate-100">{insight.kpi_name}</h4>
        {insight.category && (
          <span className="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-mist">{insight.category}</span>
        )}
        <span className="num text-[11px] text-mist-dim">{insight.period}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {insight.feedback?.feedback_factor != null &&
            insight.feedback.feedback_factor !== 1.0 && (
              <span
                title="Phase 9 feedback factor (per KPI × confidence level × persona) — a trust label, never evidence"
                className={
                  "num rounded border px-1.5 py-0.5 text-[10px] font-medium " +
                  (insight.feedback.feedback_factor > 1
                    ? "border-conf-high/30 bg-conf-high/10 text-conf-high"
                    : "border-conf-low/30 bg-conf-low/10 text-conf-low")
                }
              >
                ×{insight.feedback.feedback_factor}
              </span>
            )}
          <VoteButtons
            insight={insight}
            lastVote={lastVote}
            onVote={onVote ? (rating) => onVote(insight, rating) : undefined}
            voting={voting}
          />
          <ConfidenceBadge status={c.status} score={c.score} />
        </span>
      </div>

      {insight.insufficient_history && (
        <div className="mt-2 rounded-lg border border-conf-abstain/30 bg-conf-abstain/[0.06] px-3 py-2 text-[11px] leading-relaxed text-mist">
          <span className="font-medium text-conf-abstain">Insufficient history.</span>{" "}
          {c.message}
        </div>
      )}

      {/* movement */}
      {a && (
        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="num text-lg font-semibold text-slate-100">
            {fmtValue(a.baseline_value, unit)} <span className="text-mist-dim">→</span> {fmtValue(a.current_value, unit)}
          </span>
          <span className="num text-[11px] text-mist">
            {signed(a.absolute_change, deltaUnit || unit)} ({signed(a.pct_change, "percent")})
          </span>
          <span className="num rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-mist">
            z {a.z_score}
          </span>
        </div>
      )}

      {/* explanation bars */}
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <ExplainedBar label="Business drivers explain" pct={c.business_explained_pct} color="#4F8EF7" />
        <ExplainedBar label="Arithmetic decomposition explains" pct={c.arithmetic_explained_pct} color="#5D6F8F" />
      </div>

      {/* drivers */}
      {insight.drivers && insight.drivers.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-mist-dim">
            Decomposition drivers
          </p>
          <div className="divide-y divide-line/50">
            {insight.drivers.map((d) => (
              <DriverRow key={d.driver_name} d={d} unit={unit} />
            ))}
          </div>
        </div>
      )}

      {/* abstain box */}
      {abstain && (
        <div className="mt-3 rounded-lg border border-conf-abstain/30 bg-conf-abstain/[0.06] p-3">
          <p className="text-[11px] leading-relaxed text-mist">
            <span className="font-medium text-conf-abstain">The engine abstains from business actions.</span>{" "}
            {c.reasons && c.reasons.length > 0 && (
              <span className="text-mist-dim">
                Reasons: {c.reasons.join(" · ")}
                {c.data_completeness != null &&
                  ` · data completeness ${fmt1(c.data_completeness * 100)}% < ${c.data_completeness_threshold ?? 0.90}% threshold`}
              </span>
            )}
          </p>
        </div>
      )}

      {/* recommendations */}
      {recs.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 flex items-baseline justify-between">
            <p className="text-[10px] font-medium uppercase tracking-wider text-mist-dim">
              Recommendations ({recs.length})
            </p>
            {!abstain && recs.filter((r) => r.actionable).length > 0 && (
              <span className="text-[10px] text-mist-dim">
                {recs.filter((r) => r.actionable).length} actionable
              </span>
            )}
          </div>
          <div className="space-y-2">
            {visibleRecs.map((rec, i) => (
              <Recommendation key={`${rec.lever}-${i}`} rec={rec} unit={unit} />
            ))}
          </div>
          {recs.length > 3 && (
            <button
              onClick={() => setShowAllRecs(!showAllRecs)}
              className="mt-2 text-[11px] text-accent hover:underline"
            >
              {showAllRecs ? "Show fewer" : `Show all ${recs.length}`}
            </button>
          )}
        </div>
      )}

      {/* narrative */}
      {n && (
        <div className="mt-3 rounded-lg border border-line bg-ink-850 p-3">
          <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-medium uppercase tracking-wider text-mist-dim">
              Narration
            </span>
            {n.mock ? (
              <span className="rounded border border-conf-abstain/40 bg-conf-abstain/10 px-1.5 py-0.5 text-[9px] text-conf-abstain">
                [MOCK] {n.model}
              </span>
            ) : (
              <span className="rounded border border-line bg-ink-700 px-1.5 py-0.5 text-[9px] text-mist">
                {n.provider} · {n.model}
              </span>
            )}
            {n.grounded ? (
              <span className="rounded border border-conf-high/30 bg-conf-high/10 px-1.5 py-0.5 text-[9px] text-conf-high">
                grounded ✓
              </span>
            ) : (
              <span className="rounded border border-conf-low/30 bg-conf-low/10 px-1.5 py-0.5 text-[9px] text-conf-low">
                ungrounded · {n.violations?.length ?? 0} violation(s) — discarded by code
              </span>
            )}
          </div>
          <p className={"text-[12px] leading-relaxed text-mist-bright/90 " + (showAllNarrative ? "" : "line-clamp-4")}>
            {n.text}
          </p>
          {!showAllNarrative && n.text.length > 220 && (
            <button onClick={() => setShowAllNarrative(true)} className="mt-1 text-[11px] text-accent hover:underline">
              Show more
            </button>
          )}
        </div>
      )}

      {/* LLM vs non-LLM footer */}
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line/60 pt-2 text-[9px] text-mist-dim">
        <span className="flex items-center gap-1">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-accent" />
          Code (deterministic): detection → decomposition → confidence → actions
        </span>
        <span className="flex items-center gap-1">
          <span className={"inline-block h-1.5 w-1.5 rounded-full " + (n?.mock ? "bg-conf-abstain" : "bg-conf-high")} />
          LLM: {n?.mock ? "mock narration (no real model call)" : `narration via ${n.provider}/${n.model}`}
        </span>
        <span className="ml-auto">numbers 100% from pipeline JSON</span>
      </div>
    </article>
  );
}

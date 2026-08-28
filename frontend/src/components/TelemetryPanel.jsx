import { fmtMs, fmtTokens, money } from "../lib/format";

function Row({ label, value, sub }) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-0.5">
      <span className="text-[11px] text-mist-dim">{label}</span>
      <span className="num text-[11px] text-mist-bright">
        {value}
        {sub && <span className="ml-1 text-[10px] text-mist-dim">{sub}</span>}
      </span>
    </div>
  );
}

function StageRow({ name, st, maxMs }) {
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="w-24 shrink-0 text-[11px] text-mist">{name}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full bg-accent/80"
          style={{ width: `${Math.max(1, (st.total_ms / maxMs) * 100)}%` }}
        />
      </div>
      <span className="num w-16 shrink-0 text-right text-[10px] text-mist-dim">
        {fmtMs(st.total_ms)}
      </span>
      <span className="num w-14 shrink-0 text-right text-[10px] text-mist-dim">
        ×{st.count}
      </span>
    </div>
  );
}

export default function TelemetryPanel({ data, live }) {
  if (!data) return null;
  const stages = data.stages || {};
  const llm = data.llm || {};
  const cost = data.cost_at_scale || {};
  const lp = data.last_pipeline || {};
  const maxMs = Math.max(1, ...Object.values(stages).map((s) => s.total_ms));

  const grounding =
    llm.grounding_checked > 0
      ? `${llm.grounding_passed}/${llm.grounding_checked}`
      : "n/a";

  return (
    <section className="rounded-xl border border-line bg-ink-900 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-mist-bright">Runtime telemetry</h2>
        <span
          className={
            "rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider " +
            (live
              ? "border-conf-high/30 bg-conf-high/10 text-conf-high"
              : "border-conf-abstain/40 bg-conf-abstain/10 text-conf-abstain")
          }
        >
          {live ? "live · GET /telemetry" : "sample snapshot"}
        </span>
        {lp.total_ms != null && (
          <span className="num text-[10px] text-mist-dim">
            last pipeline: {fmtMs(lp.total_ms)} · {lp.anomalies ?? "—"} anomalies
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
        {/* stages */}
        <div>
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-mist-dim">
            Pipeline stages (instrumented)
          </p>
          {Object.entries(stages).map(([name, st]) => (
            <StageRow key={name} name={name} st={st} maxMs={maxMs} />
          ))}
          <div className="mt-1 flex items-center justify-between border-t border-line/60 pt-1.5">
            <span className="text-[11px] font-medium text-mist">Total</span>
            <span className="num text-[11px] font-semibold text-mist-bright">
              {fmtMs(Object.values(stages).reduce((a, s) => a + s.total_ms, 0))}
            </span>
          </div>
        </div>

        {/* LLM */}
        <div>
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-mist-dim">
            LLM calls
          </p>
          <div className="mb-2 flex items-baseline gap-4">
            <span className="num text-2xl font-semibold text-slate-100">{llm.calls ?? 0}</span>
            <span className="text-[11px] text-mist-dim">
              {llm.mock_calls ?? 0} mock{llm.calls > 0 ? ` · ${llm.calls - (llm.mock_calls ?? 0)} real` : " (no real model calls)"}
            </span>
          </div>
          <Row label="Prompt tokens (real)" value={fmtTokens(llm.prompt_tokens)} />
          <Row label="Completion tokens (real)" value={fmtTokens(llm.completion_tokens)} />
          <Row label="Total tokens (real)" value={fmtTokens(llm.total_tokens)} />
          <Row
            label="Mock tokens (labeled, never billed)"
            value={`${fmtTokens(llm.mock_tokens?.prompt)}/${fmtTokens(llm.mock_tokens?.completion)}`}
          />
          <Row label="Avg call latency" value={llm.avg_call_ms != null ? fmtMs(llm.avg_call_ms) : "—"} />
          <Row label="Grounding checks passed" value={grounding} />
          <Row label="Truncated responses" value={llm.truncated ?? 0} />
        </div>

        {/* cost */}
        <div>
          <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-mist-dim">
            Cost
          </p>
          <div className="mb-2 flex items-baseline gap-2">
            <span className="num text-2xl font-semibold text-slate-100">
              {cost.estimated_cost_usd != null ? money(cost.estimated_cost_usd, 4) : "$0.0000"}
            </span>
            <span className="rounded border border-line bg-ink-850 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-mist-dim">
              {cost.pricing}
            </span>
          </div>
          <Row
            label="Projected at 1,000 calls"
            value={cost.projected_cost_usd_at_1000_calls != null ? money(cost.projected_cost_usd_at_1000_calls) : "n/a — no real calls yet"}
          />
          <Row label="Input rate" value={`$${cost.input_rate_per_1m_usd ?? 0} / 1M tokens`} />
          <Row label="Output rate" value={`$${cost.output_rate_per_1m_usd ?? 0} / 1M tokens`} />
          <p className="mt-2 text-[10px] leading-relaxed text-mist-dim">
            Free tier = Ollama local/cloud model (no API billing). Configured rates
            apply automatically when a paid provider is set; mock tokens are
            excluded from real totals and cost by design.
          </p>
        </div>
      </div>
    </section>
  );
}

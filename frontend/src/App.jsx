import { useCallback, useEffect, useState } from "react";
import Header from "./components/Header";
import KpiTrendCard from "./components/KpiTrendCard";
import InsightFeed from "./components/InsightFeed";
import TelemetryPanel from "./components/TelemetryPanel";
import DemoScenarios from "./components/DemoScenarios";
import {
  loadMeta,
  loadTimeseries,
  loadInsights,
  loadTelemetry,
  postFeedback,
} from "./api/client";

const KPI_ORDER = ["Revenue", "Units Sold", "Gross Margin %", "Customer Churn Rate"];

function DataChip({ label, live }) {
  return (
    <span
      className={
        "rounded border px-2 py-0.5 text-[10px] font-medium " +
        (live
          ? "border-conf-high/30 bg-conf-high/10 text-conf-high"
          : "border-conf-abstain/40 bg-conf-abstain/10 text-conf-abstain")
      }
    >
      {label}: {live ? "live" : "sample snapshot"}
    </span>
  );
}

export default function App() {
  const [persona, setPersona] = useState("CFO");
  const [meta, setMeta] = useState(null);
  const [timeseries, setTimeseries] = useState(null);
  const [insights, setInsights] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [live, setLive] = useState({ insights: null, telemetry: null });
  const [loading, setLoading] = useState(true);
  const [lastVotes, setLastVotes] = useState({});
  const [voting, setVoting] = useState(false);
  const [voteError, setVoteError] = useState(null);

  useEffect(() => {
    let active = true;
    setInsights(null);
    setLastVotes({});
    setVoteError(null);
    (async () => {
      const [m, t, i, tel] = await Promise.all([
        loadMeta(),
        loadTimeseries(),
        loadInsights(persona),
        loadTelemetry(),
      ]);
      if (!active) return;
      setMeta(m.data);
      setTimeseries(t.data);
      setInsights(i.data);
      setTelemetry(tel.data);
      setLive({ insights: i.live, telemetry: tel.live });
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [persona]);

  // Phase 12: a vote is recorded server-side (confidence context derived
  // there), then the feed is re-fetched — the server rebuild is pure
  // re-ranking, zero extra LLM calls.
  const handleVote = useCallback(
    async (insight, rating) => {
      if (voting) return;
      setVoting(true);
      setVoteError(null);
      try {
        await postFeedback({
          insight_id: insight.insight_id,
          persona,
          rating,
        });
        setLastVotes((v) => ({ ...v, [insight.insight_id]: rating }));
        const { data, live: isLive } = await loadInsights(persona);
        setInsights(data);
        setLive((l) => ({ ...l, insights: isLive }));
      } catch (e) {
        setVoteError(
          "Feedback unavailable (backend offline)" +
            (e.detail ? ` — ${e.detail}` : "")
        );
      } finally {
        setVoting(false);
      }
    },
    [persona, voting]
  );

  const blockedByKpi =
    insights?.blocked?.reduce((acc, b) => ({ ...acc, [b.kpi_name]: b }), {}) || {};

  return (
    <div className="min-h-screen">
      <Header persona={persona} onPersona={setPersona} meta={meta} />

      {loading ? (
        <div className="flex h-[60vh] items-center justify-center">
          <p className="animate-pulse text-sm text-mist-dim">
            running deterministic pipeline &amp; fetching data…
          </p>
        </div>
      ) : (
        <main className="mx-auto grid max-w-[1600px] grid-cols-12 gap-4 px-4 py-4">
          {/* KPI trend cards */}
          <section className="col-span-12 grid grid-cols-1 gap-4 md:grid-cols-2 xl:col-span-7">
            {KPI_ORDER.map((kpi) => (
              <KpiTrendCard
                key={kpi}
                kpi={kpi}
                series={timeseries?.[kpi]}
                blocked={blockedByKpi[kpi]}
              />
            ))}
          </section>

          {/* insight feed */}
          <section className="col-span-12 xl:col-span-5">
            {insights ? (
              <InsightFeed
                insights={insights.insights}
                blocked={insights.blocked}
                persona={persona}
                lastVotes={lastVotes}
                onVote={handleVote}
                voting={voting}
                voteError={voteError}
              />
            ) : (
              <div className="rounded-xl border border-line bg-ink-900 p-4">
                <p className="animate-pulse text-sm text-mist-dim">loading insights…</p>
              </div>
            )}
          </section>

          {/* telemetry */}
          <section className="col-span-12">
            <TelemetryPanel data={telemetry} live={live.telemetry} />
          </section>

          {/* demo guide */}
          <section className="col-span-12">
            <DemoScenarios />
          </section>

          {/* data provenance footer */}
          <footer className="col-span-12 flex flex-wrap items-center gap-2 border-t border-line/60 pt-3">
            <DataChip label="insights" live={live.insights} />
            <DataChip label="telemetry" live={live.telemetry} />
            {!live.insights && meta?.generated_at && (
              <span className="num text-[10px] text-mist-dim">
                sample generated {meta.generated_at} · real pipeline run, mock narration
                (clearly labeled) · Phase 12 serves this live
              </span>
            )}
            <span className="ml-auto text-[10px] text-mist-dim">
              BusinessIntelligence.ai · deterministic core / LLM narrator · zero API spend
            </span>
          </footer>
        </main>
      )}
    </div>
  );
}

import PersonaSwitcher from "./PersonaSwitcher";

function FreshnessChip({ name, info }) {
  if (!info) return null;
  const fresh = info.status === "fresh";
  return (
    <div
      className="flex items-center gap-1.5 rounded-md border border-line bg-ink-850 px-2 py-1"
      title={`${info.grain} grain · latest ${info.latest_data} · ${info.staleness_hours}h stale`}
    >
      <span
        className={
          "inline-block h-1.5 w-1.5 rounded-full " +
          (fresh ? "bg-conf-high" : "bg-conf-medium")
        }
      />
      <span className="text-[11px] text-mist">{name}</span>
      <span className="num text-[10px] text-mist-dim">
        {info.staleness_hours}h
      </span>
    </div>
  );
}

export default function Header({ persona, onPersona, meta }) {
  const freshness = meta?.source_freshness || {};
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-ink-950/90 backdrop-blur">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-3">
          <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="13" fill="none" stroke="#4F8EF7" strokeWidth="2.5" strokeDasharray="58 24" strokeLinecap="round" />
            <circle cx="16" cy="16" r="7.5" fill="none" stroke="#8FA3C0" strokeWidth="1.5" strokeDasharray="30 17" strokeLinecap="round" />
            <circle cx="16" cy="16" r="2.4" fill="#34D399" />
          </svg>
          <div>
            <h1 className="text-sm font-semibold tracking-wide text-slate-100">
              BusinessIntelligence.ai
            </h1>
            <p className="text-[11px] text-mist-dim">
              KPI Intelligence-to-Action Engine · deterministic core, LLM narrator
            </p>
          </div>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-3">
          <div className="hidden items-center gap-1.5 lg:flex">
            {Object.entries(freshness).map(([name, info]) => (
              <FreshnessChip key={name} name={name} info={info} />
            ))}
          </div>
          <PersonaSwitcher persona={persona} onChange={onPersona} />
        </div>
      </div>
    </header>
  );
}

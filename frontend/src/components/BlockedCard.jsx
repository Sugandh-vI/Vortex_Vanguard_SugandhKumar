export default function BlockedCard({ blocked, compact = false }) {
  const d = blocked?.decision || {};
  return (
    <div className="rounded-xl border border-blocked/30 bg-blocked/[0.04] p-4">
      <div className="flex items-start gap-3">
        <svg width="18" height="18" viewBox="0 0 24 24" className="mt-0.5 shrink-0 text-blocked" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="4" y="11" width="16" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-blocked">
            Access blocked
            <span className="num rounded bg-blocked/10 px-1.5 py-0.5 text-[10px] normal-case tracking-normal text-blocked/90">
              {blocked?.kpi_name}
            </span>
          </p>
          {!compact && (
            <>
              <p className="mt-1.5 text-xs leading-relaxed text-mist">{d.reason}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <span className="num rounded border border-line bg-ink-850 px-1.5 py-0.5 text-[10px] text-mist-dim">
                  source: {d.source}
                </span>
                <span className="rounded border border-line bg-ink-850 px-1.5 py-0.5 text-[10px] text-mist-dim">
                  blocked before narration · logged to access_log
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

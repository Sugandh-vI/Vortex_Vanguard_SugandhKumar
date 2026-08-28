const PERSONAS = ["CFO", "Category Manager"];

export default function PersonaSwitcher({ persona, onChange }) {
  return (
    <div className="flex items-center rounded-lg border border-line bg-ink-850 p-0.5">
      {PERSONAS.map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          className={
            "rounded-md px-3 py-1.5 text-xs font-medium transition-colors " +
            (persona === p
              ? "bg-accent-soft text-accent shadow-inner"
              : "text-mist hover:text-mist-bright")
          }
        >
          {p}
        </button>
      ))}
    </div>
  );
}

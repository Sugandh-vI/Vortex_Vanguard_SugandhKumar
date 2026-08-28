const STYLES = {
  high: "border-conf-high/40 bg-conf-high/10 text-conf-high",
  medium: "border-conf-medium/40 bg-conf-medium/10 text-conf-medium",
  low: "border-conf-low/40 bg-conf-low/10 text-conf-low",
  abstain: "border-conf-abstain/50 bg-conf-abstain/10 text-conf-abstain border-dashed",
};

const LABELS = {
  high: "High",
  medium: "Medium",
  low: "Low",
  abstain: "Abstain",
};

export default function ConfidenceBadge({ status, score, size = "sm" }) {
  const s = STYLES[status] || STYLES.abstain;
  const label = LABELS[status] || status;
  return (
    <span
      className={
        "num inline-flex items-center gap-1.5 rounded-full border font-medium " +
        s +
        (size === "sm" ? " px-2 py-0.5 text-[11px]" : " px-3 py-1 text-sm")
      }
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current" />
      {label}
      {score != null && <span className="opacity-70">· {score}</span>}
    </span>
  );
}

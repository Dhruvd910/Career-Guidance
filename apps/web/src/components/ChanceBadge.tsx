const BAND_CLASS: Record<string, string> = {
  high_probability: "chance-high",
  possible: "chance-possible",
  ambitious: "chance-ambitious",
};

export function ChanceBadge({ band, label, emoji }: { band: string; label: string; emoji: string }) {
  const cls = BAND_CLASS[band] ?? "chance-possible";
  return (
    <span className={`chance-badge ${cls}`}>
      <span>{emoji}</span>
      <span>{label}</span>
    </span>
  );
}

export function DemoDataBadge() {
  return <span className="demo-badge" title="Sample data for development — not real admissions data">DEMO DATA</span>;
}

"use client";

import { PredictionResponse, PredictionResultItem } from "@/lib/api";
import { ChanceBadge, DemoDataBadge } from "./ChanceBadge";
import { Card, Disclaimer } from "./ui";
import Link from "next/link";

function ResultCard({ result }: { result: PredictionResultItem }) {
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <Link href={`/colleges/${result.college_id}`} className="font-semibold hover:underline">
            {result.college_name}
          </Link>
          <p className="text-sm text-muted">
            {result.course_name}{result.branch_name ? ` · ${result.branch_name}` : ""} · {result.city}, {result.state}
          </p>
        </div>
        {result.is_demo_data && <DemoDataBadge />}
      </div>
      <div className="flex items-center gap-2 flex-wrap text-xs text-muted">
        <ChanceBadge band={result.band} label={result.band_label} emoji={result.band_emoji} />
        <span>Category: {result.category}</span>
        <span>Quota: {result.quota}</span>
        <span>Confidence: {result.confidence}</span>
      </div>
      <p className="text-sm">{result.explanation.reasoning}</p>
    </Card>
  );
}

export function PredictionResults({ prediction }: { prediction: PredictionResponse }) {
  const groups: { key: PredictionResultItem["band"]; title: string }[] = [
    { key: "high_probability", title: "🟢 High Probability" },
    { key: "possible", title: "🟡 Possible" },
    { key: "ambitious", title: "🔴 Ambitious / Dream" },
  ];

  if (prediction.results.length === 0) {
    return (
      <Card>
        <p className="text-muted text-sm">
          No matching options found in the current dataset for this rank/category combination.
          Try adjusting your preferences, or check back once more colleges are added.
        </p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {groups.map((g) => {
        const items = prediction.results.filter((r) => r.band === g.key);
        if (items.length === 0) return null;
        return (
          <div key={g.key}>
            <h3 className="font-semibold mb-3">{g.title} ({items.length})</h3>
            <div className="grid md:grid-cols-2 gap-3">
              {items.map((r, i) => (
                <ResultCard key={`${r.college_id}-${r.quota}-${i}`} result={r} />
              ))}
            </div>
          </div>
        );
      })}
      <Disclaimer>{prediction.disclaimer}</Disclaimer>
    </div>
  );
}

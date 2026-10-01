"use client";

import Link from "next/link";
import { CollegeSummary, PredictionResultItem } from "@/lib/api";
import { ChanceBadge, DemoDataBadge } from "./ChanceBadge";
import { Button, Card } from "./ui";

// The §36 college card: name/location/type/branch/chance/cutoff/fees/hostel/rating +
// save/compare/view actions. `prediction` is optional — plain browsing (no rank yet)
// just omits the chance badge and cutoff line rather than guessing one.
export function CollegeCard({
  college,
  prediction,
  onSave,
  onCompareToggle,
  isComparing,
}: {
  college: CollegeSummary;
  prediction?: PredictionResultItem;
  onSave?: () => void;
  onCompareToggle?: () => void;
  isComparing?: boolean;
}) {
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold leading-tight">{college.canonical_name}</h3>
          <p className="text-sm text-muted">
            {college.city}, {college.state} · {college.college_type} ({college.ownership})
          </p>
        </div>
        {college.is_demo_data && <DemoDataBadge />}
      </div>

      {prediction && (
        <div className="flex flex-col gap-1 text-sm">
          <div className="flex items-center gap-2">
            <ChanceBadge band={prediction.band} label={prediction.band_label} emoji={prediction.band_emoji} />
            <span className="text-muted">{prediction.course_name}{prediction.branch_name ? ` · ${prediction.branch_name}` : ""}</span>
          </div>
          <p className="text-muted">
            Median historical closing rank:{" "}
            {Math.round(
              Object.values(prediction.explanation.historical_closing_ranks).reduce((a, b) => a + b, 0) /
                Object.values(prediction.explanation.historical_closing_ranks).length
            ).toLocaleString()}
          </p>
        </div>
      )}

      {college.average_rating != null && (
        <p className="text-sm text-muted">★ {college.average_rating.toFixed(1)} ({college.review_count} reviews)</p>
      )}

      <div className="flex items-center gap-2 mt-auto pt-2">
        <Link href={`/colleges/${college.id}`}>
          <Button variant="secondary">View Details</Button>
        </Link>
        {onSave && <Button variant="ghost" onClick={onSave}>Save</Button>}
        {onCompareToggle && (
          <Button variant="ghost" onClick={onCompareToggle}>
            {isComparing ? "Remove from compare" : "Compare"}
          </Button>
        )}
      </div>
    </Card>
  );
}

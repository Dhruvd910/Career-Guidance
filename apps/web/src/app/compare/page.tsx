"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError, CollegeCompareRow } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Card, ErrorMessage, PageHeading, Spinner } from "@/components/ui";
import { DemoDataBadge } from "@/components/ChanceBadge";

function formatMoney(n: number | null) {
  return n == null ? "N/A" : `₹${n.toLocaleString("en-IN")}`;
}

const ROWS: { key: keyof CollegeCompareRow; label: string; render?: (v: CollegeCompareRow) => React.ReactNode }[] = [
  { key: "lowest_closing_rank_seen", label: "Toughest closing rank seen", render: (r) => r.lowest_closing_rank_seen?.toLocaleString() ?? "N/A" },
  { key: "approximate_annual_cost", label: "Approx. annual cost", render: (r) => formatMoney(r.approximate_annual_cost) },
  { key: "hostel_available", label: "Hostel available", render: (r) => (r.hostel_available ? "Yes" : "No") },
  { key: "placement_percentage", label: "Placement %", render: (r) => (r.placement_percentage != null ? `${r.placement_percentage}%` : "N/A") },
  { key: "average_package", label: "Average package", render: (r) => formatMoney(r.average_package) },
  { key: "average_rating", label: "Student rating", render: (r) => (r.average_rating != null ? `★ ${r.average_rating}` : "No reviews yet") },
];

function CompareContent() {
  const searchParams = useSearchParams();
  const ids = (searchParams.get("ids") || "").split(",").map(Number).filter(Boolean);
  const [rows, setRows] = useState<CollegeCompareRow[]>([]);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ids.length < 2) {
      setLoading(false);
      return;
    }
    api.colleges
      .compare(ids)
      .then((res) => {
        setRows(res.rows);
        setAiSummary(res.ai_summary);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not compare these colleges."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(",")]);

  if (ids.length < 2) return <ErrorMessage message="Select at least 2 colleges from the College Discovery page to compare." />;
  if (loading) return <Spinner />;

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title="College Comparison" />
      <ErrorMessage message={error} />

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th className="py-2 pr-4"></th>
                {rows.map((r) => (
                  <th key={r.college.id} className="py-2 pr-4">
                    <div className="flex items-center gap-2">
                      {r.college.canonical_name}
                      {r.college.is_demo_data && <DemoDataBadge />}
                    </div>
                    <p className="text-xs text-muted font-normal">{r.college.city}, {r.college.state}</p>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => (
                <tr key={String(row.key)} className="border-t border-card-border">
                  <td className="py-2 pr-4 font-medium text-muted">{row.label}</td>
                  {rows.map((r) => (
                    <td key={r.college.id} className="py-2 pr-4">{row.render ? row.render(r) : String(r[row.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {aiSummary && (
        <Card>
          <h3 className="font-semibold mb-2">AI Summary</h3>
          <p className="text-sm whitespace-pre-wrap">{aiSummary}</p>
          <p className="text-xs text-muted mt-2">Generated from the table above — not additional outside information.</p>
        </Card>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<Spinner />}>
        <CompareContent />
      </Suspense>
    </ProtectedRoute>
  );
}

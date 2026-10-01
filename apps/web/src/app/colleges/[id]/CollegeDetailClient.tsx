"use client";

import { useEffect, useState } from "react";
import {
  api, ApiError, CollegeDetail, CollegeReview, CutoffOut, FeeOut, HostelOut, NearbyPlaceOut, PlacementOut,
} from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { DemoDataBadge } from "@/components/ChanceBadge";
import { ProvenanceLine } from "@/components/Provenance";
import { Button, Card, ErrorMessage, PageHeading, Spinner } from "@/components/ui";

const TABS = ["Overview", "Admission", "Fees", "Hostel", "Placements", "Nearby", "Reviews"] as const;
type Tab = (typeof TABS)[number];

function formatMoney(n: number | null) {
  if (n == null) return "Not available";
  return `₹${n.toLocaleString("en-IN")}`;
}

function CollegeDetailContent({ collegeId }: { collegeId: number }) {
  const [tab, setTab] = useState<Tab>("Overview");
  const [college, setCollege] = useState<CollegeDetail | null>(null);
  const [cutoffs, setCutoffs] = useState<CutoffOut[]>([]);
  const [fees, setFees] = useState<FeeOut[]>([]);
  const [hostels, setHostels] = useState<HostelOut[]>([]);
  const [placements, setPlacements] = useState<PlacementOut[]>([]);
  const [nearby, setNearby] = useState<NearbyPlaceOut[]>([]);
  const [reviews, setReviews] = useState<CollegeReview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reviewRating, setReviewRating] = useState(5);
  const [reviewText, setReviewText] = useState("");
  const [submittingReview, setSubmittingReview] = useState(false);

  async function loadAll() {
    setLoading(true);
    try {
      const [c, cu, f, h, p, n, r] = await Promise.all([
        api.colleges.get(collegeId),
        api.colleges.cutoffs(collegeId),
        api.colleges.fees(collegeId),
        api.colleges.hostel(collegeId),
        api.colleges.placements(collegeId),
        api.colleges.nearby(collegeId),
        api.colleges.reviews(collegeId),
      ]);
      setCollege(c);
      setCutoffs(cu);
      setFees(f);
      setHostels(h);
      setPlacements(p);
      setNearby(n);
      setReviews(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load this college.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collegeId]);

  async function submitReview(e: React.FormEvent) {
    e.preventDefault();
    setSubmittingReview(true);
    try {
      await api.colleges.addReview(collegeId, { rating: reviewRating, text: reviewText, tags: [] });
      setReviewText("");
      const r = await api.colleges.reviews(collegeId);
      setReviews(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit your review.");
    } finally {
      setSubmittingReview(false);
    }
  }

  if (loading) return <Spinner />;
  if (error && !college) return <ErrorMessage message={error} />;
  if (!college) return null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <PageHeading
          title={college.canonical_name}
          subtitle={`${college.city}, ${college.state} · ${college.college_type} (${college.ownership})`}
        />
        {college.is_demo_data && <DemoDataBadge />}
      </div>

      <div className="flex gap-1 overflow-x-auto border-b border-card-border">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 ${tab === t ? "border-primary text-primary" : "border-transparent text-muted"}`}
          >
            {t}
          </button>
        ))}
      </div>

      <ErrorMessage message={error} />

      {tab === "Overview" && (
        <div className="grid md:grid-cols-2 gap-4">
          <Card>
            <h3 className="font-semibold mb-2">About</h3>
            <p className="text-sm mb-1">Established: {college.established_year ?? "Not available"}</p>
            <p className="text-sm mb-1">Affiliated university: {college.affiliated_university ?? "N/A"}</p>
            <p className="text-sm mb-1">Accreditation: {college.accreditation ?? "Not available"}</p>
            {college.official_website && (
              <a href={college.official_website} className="text-sm text-primary" target="_blank" rel="noreferrer">Official website</a>
            )}
          </Card>
          <Card>
            <h3 className="font-semibold mb-2">Courses Offered</h3>
            <ul className="text-sm flex flex-col gap-1">
              {college.courses_offered.map((cc) => (
                <li key={cc.id} className="flex justify-between">
                  <span>{cc.course_name}{cc.branch ? ` · ${cc.branch.name}` : ""}</span>
                  <span className="text-muted">{cc.total_seats ? `${cc.total_seats} seats` : ""}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      )}

      {tab === "Admission" && (
        <Card>
          <h3 className="font-semibold mb-4">Historical Cutoffs</h3>
          {cutoffs.length === 0 ? <p className="text-sm text-muted">No cutoff data available yet.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted text-left">
                  <tr>
                    <th className="py-1 pr-3">Year</th><th className="py-1 pr-3">Round</th><th className="py-1 pr-3">Category</th>
                    <th className="py-1 pr-3">Quota</th><th className="py-1 pr-3">Opening</th><th className="py-1 pr-3">Closing</th>
                  </tr>
                </thead>
                <tbody>
                  {cutoffs.map((c) => (
                    <tr key={c.id} className="border-t border-card-border">
                      <td className="py-1 pr-3">{c.year}</td>
                      <td className="py-1 pr-3">{c.round}</td>
                      <td className="py-1 pr-3">{c.category}</td>
                      <td className="py-1 pr-3">{c.quota}</td>
                      <td className="py-1 pr-3">{c.opening_rank ?? "-"}</td>
                      <td className="py-1 pr-3">{c.closing_rank.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {cutoffs[0] && <ProvenanceLine provenance={cutoffs[0].provenance} />}
            </div>
          )}
        </Card>
      )}

      {tab === "Fees" && (
        <div className="grid md:grid-cols-2 gap-4">
          {fees.length === 0 ? <p className="text-sm text-muted">No fee data available yet.</p> : fees.map((f) => (
            <Card key={f.id}>
              <p className="text-sm mb-1">Tuition: {formatMoney(f.tuition_fee)}</p>
              <p className="text-sm mb-1">Admission fee: {formatMoney(f.admission_fee)}</p>
              <p className="text-sm mb-1">Hostel fee: {formatMoney(f.hostel_fee)}</p>
              <p className="text-sm mb-1">Mess fee: {formatMoney(f.mess_fee)}</p>
              <p className="text-sm mb-1">Security deposit: {formatMoney(f.security_deposit)}</p>
              <p className="text-sm font-semibold mt-2">Approx. annual cost: {formatMoney(f.approximate_annual_cost)}</p>
              <ProvenanceLine provenance={f.provenance} />
            </Card>
          ))}
        </div>
      )}

      {tab === "Hostel" && (
        <div className="grid md:grid-cols-2 gap-4">
          {hostels.length === 0 ? <p className="text-sm text-muted">No hostel data available yet.</p> : hostels.map((h) => (
            <Card key={h.id}>
              <h3 className="font-semibold mb-2 capitalize">{h.hostel_type} hostel</h3>
              <p className="text-sm mb-1">Capacity: {h.capacity ?? "Not available"}</p>
              <p className="text-sm mb-1">Room types: {h.room_types.join(", ") || "Not available"}</p>
              <p className="text-sm mb-1">Annual fee: {formatMoney(h.fee_annual)}</p>
              <p className="text-sm mb-1">Facilities: {h.facilities.join(", ") || "Not available"}</p>
              <p className="text-sm mb-1">Distance from academic block: {h.distance_from_academic_block_km ?? "?"} km</p>
              <ProvenanceLine provenance={h.provenance} />
            </Card>
          ))}
        </div>
      )}

      {tab === "Placements" && (
        <div className="grid md:grid-cols-2 gap-4">
          {placements.length === 0 ? <p className="text-sm text-muted">No placement/outcome data available yet.</p> : placements.map((p) => (
            <Card key={p.id}>
              {p.placement_percentage != null ? (
                <>
                  <h3 className="font-semibold mb-2">Placement outcomes</h3>
                  <p className="text-sm mb-1">Placement rate: {p.placement_percentage}%</p>
                  <p className="text-sm mb-1">Average package: {formatMoney(p.average_package)}</p>
                  <p className="text-sm mb-1">Median package: {formatMoney(p.median_package)}</p>
                  <p className="text-sm mb-1">Highest package: {formatMoney(p.highest_package)}</p>
                  <p className="text-sm mb-1">Recruiters: {p.major_recruiters.join(", ") || "Not available"}</p>
                </>
              ) : (
                <>
                  <h3 className="font-semibold mb-2">Career outcomes</h3>
                  {Object.entries(p.extra).map(([k, v]) => (
                    <p key={k} className="text-sm mb-1 capitalize">{k.replace(/_/g, " ")}: {String(v)}</p>
                  ))}
                </>
              )}
              <ProvenanceLine provenance={p.provenance} />
            </Card>
          ))}
        </div>
      )}

      {tab === "Nearby" && (
        <Card>
          <h3 className="font-semibold mb-4">Nearby facilities & accommodation</h3>
          {nearby.length === 0 ? <p className="text-sm text-muted">No nearby-facility data available yet.</p> : (
            <ul className="flex flex-col gap-2 text-sm">
              {nearby.map((n) => (
                <li key={n.id} className="flex justify-between border-b border-card-border pb-2">
                  <span className="capitalize">{n.place_type.replace(/_/g, " ")}: {n.name}</span>
                  <span className="text-muted">
                    {n.distance_km != null && `${n.distance_km} km`}
                    {n.approx_monthly_rent != null && ` · ~₹${n.approx_monthly_rent}/mo`}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted mt-3">Sample data — not live availability. Never treat rent/availability figures as current.</p>
        </Card>
      )}

      {tab === "Reviews" && (
        <div className="flex flex-col gap-4">
          <Card>
            <h3 className="font-semibold mb-3">Leave a review</h3>
            <form onSubmit={submitReview} className="flex flex-col gap-3">
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button type="button" key={n} onClick={() => setReviewRating(n)} className={n <= reviewRating ? "text-yellow-500" : "text-muted"}>★</button>
                ))}
              </div>
              <textarea
                className="w-full rounded-lg border border-card-border bg-card px-3 py-2 text-sm"
                rows={3}
                placeholder="Share your experience (hostel, mess, campus life...)"
                value={reviewText}
                onChange={(e) => setReviewText(e.target.value)}
              />
              <Button type="submit" disabled={submittingReview} className="w-fit">Submit review</Button>
            </form>
          </Card>
          <p className="text-xs text-muted">Reviews are student-submitted opinions, not verified facts.</p>
          {reviews.map((r) => (
            <Card key={r.id}>
              <p className="text-sm">{"★".repeat(r.rating)}{"☆".repeat(5 - r.rating)}</p>
              <p className="text-sm mt-1">{r.text}</p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export function CollegeDetailClient({ collegeId }: { collegeId: number }) {
  return (
    <ProtectedRoute>
      <CollegeDetailContent collegeId={collegeId} />
    </ProtectedRoute>
  );
}

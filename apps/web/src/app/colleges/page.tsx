"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, CollegeSummary } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { CollegeCard } from "@/components/CollegeCard";
import { Button, ErrorMessage, Input, Label, PageHeading, Select, Spinner } from "@/components/ui";

function CollegesContent() {
  const router = useRouter();
  const [colleges, setColleges] = useState<CollegeSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<number[]>([]);

  const [q, setQ] = useState("");
  const [examCode, setExamCode] = useState("");
  const [ownership, setOwnership] = useState("");
  const [state, setState] = useState("");

  async function search() {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (q) params.q = q;
      if (examCode) params.exam_code = examCode;
      if (ownership) params.ownership = ownership;
      if (state) params.state = state;
      const results = await api.colleges.search(params);
      setColleges(results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load colleges.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggleCompare(id: number) {
    setCompareIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : prev.length < 4 ? [...prev, id] : prev));
  }

  return (
    <div className="flex flex-col gap-6 pb-20">
      <PageHeading title="College Discovery" subtitle="Search and filter colleges by exam, location, and ownership." />

      <div className="grid sm:grid-cols-4 gap-3 items-end">
        <div className="sm:col-span-2">
          <Label>Search</Label>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="College name or city" onKeyDown={(e) => e.key === "Enter" && search()} />
        </div>
        <div>
          <Label>Exam</Label>
          <Select value={examCode} onChange={(e) => setExamCode(e.target.value)}>
            <option value="">Any</option>
            <option value="JEE_MAIN">JEE Main</option>
            <option value="JEE_ADVANCED">JEE Advanced</option>
            <option value="NEET_UG">NEET-UG</option>
          </Select>
        </div>
        <div>
          <Label>Ownership</Label>
          <Select value={ownership} onChange={(e) => setOwnership(e.target.value)}>
            <option value="">Any</option>
            <option value="government">Government</option>
            <option value="private">Private</option>
          </Select>
        </div>
        <div>
          <Label>State</Label>
          <Input value={state} onChange={(e) => setState(e.target.value)} placeholder="e.g. Telangana" />
        </div>
        <Button onClick={search}>Search</Button>
      </div>

      <ErrorMessage message={error} />

      {loading ? (
        <Spinner />
      ) : colleges.length === 0 ? (
        <p className="text-muted text-sm">No colleges matched. Try broadening your filters.</p>
      ) : (
        <div className="grid md:grid-cols-3 gap-4">
          {colleges.map((c) => (
            <CollegeCard key={c.id} college={c} onCompareToggle={() => toggleCompare(c.id)} isComparing={compareIds.includes(c.id)} />
          ))}
        </div>
      )}

      {compareIds.length >= 2 && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 bg-card border border-card-border shadow-lg rounded-full px-5 py-3 flex items-center gap-4">
          <span className="text-sm">{compareIds.length} colleges selected</span>
          <Button onClick={() => router.push(`/compare?ids=${compareIds.join(",")}`)}>Compare</Button>
        </div>
      )}
    </div>
  );
}

export default function CollegesPage() {
  return (
    <ProtectedRoute>
      <CollegesContent />
    </ProtectedRoute>
  );
}

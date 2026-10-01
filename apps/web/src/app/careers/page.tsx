"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, CareerAssessmentOut, CareerFitResult, CareerOption } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Button, Card, ErrorMessage, PageHeading, RangeSlider, Spinner } from "@/components/ui";

const SUBJECTS = ["maths", "physics", "chemistry", "biology", "computer", "commerce", "english", "art"];
const TRAITS = ["analytical", "problem_solving", "creativity", "communication", "practical", "research", "people_oriented", "leadership"];

const TYPE_COPY: Record<string, { title: string; subtitle: string }> = {
  class8_9_exploration: {
    title: "Career Exploration",
    subtitle: "No decisions needed yet — this just maps out what you're drawn to.",
  },
  class10_stream: {
    title: "Stream Recommendation",
    subtitle: "Helps suggest PCM / PCB / Commerce / Arts based on your interests and strengths.",
  },
  class11_12_career: {
    title: "Career Counselling",
    subtitle: "A structured look at career families that may fit you, with honest tradeoffs.",
  },
};

function FitResultCard({ result }: { result: CareerFitResult }) {
  const labelColor = result.fit_label === "Strong fit" ? "text-chance-high-fg" : result.fit_label === "Moderate fit" ? "text-chance-possible-fg" : "text-muted";
  return (
    <Card>
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-semibold">{result.career_name}</h3>
        <span className={`text-sm font-medium ${labelColor}`}>{result.fit_label} ({result.fit_score}/100 exploration fit)</span>
      </div>
      <p className="text-sm mb-3">{result.rationale}</p>
      <div className="grid sm:grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-muted text-xs mb-1">Education path</p>
          <p>{result.education_path}</p>
        </div>
        <div>
          <p className="text-muted text-xs mb-1">Entrance exams</p>
          <p>{result.required_entrance_exams.join(", ") || "None specific"}</p>
        </div>
        <div>
          <p className="text-muted text-xs mb-1">Possible challenges</p>
          <ul className="list-disc list-inside">{result.possible_challenges.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
        <div>
          <p className="text-muted text-xs mb-1">Explore next</p>
          <ul className="list-disc list-inside">{result.explore_next.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      </div>
      {result.alternatives.length > 0 && (
        <p className="text-xs text-muted mt-3">Related alternatives: {result.alternatives.join(", ")}</p>
      )}
    </Card>
  );
}

function CareersContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const assessmentType = searchParams.get("type");

  const [ratings, setRatings] = useState<Record<string, number>>({});
  const [assessment, setAssessment] = useState<CareerAssessmentOut | null>(null);
  const [allCareers, setAllCareers] = useState<CareerOption[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(!assessmentType);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!assessmentType) {
      api.careers.list().then(setAllCareers).catch(() => {}).finally(() => setLoading(false));
    }
  }, [assessmentType]);

  function setRating(key: string, value: number) {
    setRatings((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const subject_interest: Record<string, number> = {};
      const traits: Record<string, number> = {};
      for (const s of SUBJECTS) subject_interest[s] = ratings[`subj_${s}`] ?? 5;
      for (const t of TRAITS) traits[t] = ratings[`trait_${t}`] ?? 5;

      const result = await api.careers.submitAssessment({
        assessment_type: assessmentType || "class11_12_career",
        responses: { subject_interest, traits },
      });
      setAssessment(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not run the assessment right now.");
    } finally {
      setSubmitting(false);
    }
  }

  if (assessmentType) {
    const copy = TYPE_COPY[assessmentType] ?? TYPE_COPY.class11_12_career;
    return (
      <div className="flex flex-col gap-6">
        <PageHeading title={copy.title} subtitle={copy.subtitle} />
        <ErrorMessage message={error} />

        {!assessment ? (
          <Card>
            <h3 className="font-semibold mb-4">Rate your interest (0 = not at all, 10 = love it)</h3>
            <div className="grid sm:grid-cols-2 gap-4 mb-6">
              {SUBJECTS.map((s) => (
                <RangeSlider key={s} label={s[0].toUpperCase() + s.slice(1)} value={ratings[`subj_${s}`] ?? 5} onChange={(v) => setRating(`subj_${s}`, v)} />
              ))}
            </div>
            <h3 className="font-semibold mb-4">Rate how much each describes you</h3>
            <div className="grid sm:grid-cols-2 gap-4 mb-6">
              {TRAITS.map((t) => (
                <RangeSlider key={t} label={t.replace("_", " ")} value={ratings[`trait_${t}`] ?? 5} onChange={(v) => setRating(`trait_${t}`, v)} />
              ))}
            </div>
            <Button onClick={handleSubmit} disabled={submitting}>{submitting ? "Analyzing…" : "See My Results"}</Button>
          </Card>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted">
              These are exploration-fit signals based on your own ratings — not a scientific verdict. The
              final decision, ideally with your parents/counsellor, is yours.
            </p>
            {assessment.results.map((r) => <FitResultCard key={r.career_option_id} result={r} />)}
            <Button variant="secondary" onClick={() => { setAssessment(null); setRatings({}); }}>Retake assessment</Button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title="Career Discovery" subtitle="Browse career families, or run a fresh assessment." />
      <Button className="w-fit" onClick={() => router.push("/careers?type=class11_12_career")}>
        Run Career Assessment
      </Button>
      {loading ? (
        <Spinner />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {allCareers.map((c) => (
            <Card key={c.id}>
              <h3 className="font-semibold mb-1">{c.name}</h3>
              <p className="text-xs text-muted mb-2">{c.category}</p>
              <p className="text-sm mb-2">{c.description}</p>
              <p className="text-xs text-muted">Entrance exams: {c.typical_entrance_exam_codes.join(", ") || "None specific"}</p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CareersPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<Spinner />}>
        <CareersContent />
      </Suspense>
    </ProtectedRoute>
  );
}

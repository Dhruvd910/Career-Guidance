"use client";

import { useEffect, useState } from "react";
import { api, ApiError, PredictionResponse } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button, Card, ErrorMessage, Input, Label, Select } from "@/components/ui";
import { PredictionResults } from "@/components/PredictionResults";

const CATEGORIES = ["General", "EWS", "OBC", "SC", "ST"];
const STATUSES = [
  { value: "planning", label: "Planning to prepare" },
  { value: "preparing", label: "Currently preparing" },
  { value: "appeared", label: "Appeared, awaiting result" },
  { value: "qualified", label: "Have my result / rank" },
];

export function ExamPredictorForm({
  examCode,
  examLabel,
  predict,
}: {
  examCode: string;
  examLabel: string;
  predict: (data: Record<string, unknown>) => Promise<PredictionResponse>;
}) {
  const { profile, refreshProfile } = useAuth();
  const [status, setStatus] = useState("qualified");
  const [rank, setRank] = useState("");
  const [percentile, setPercentile] = useState("");
  // Category lives on the student profile (it's a personal attribute, not exam-specific) —
  // prefilled from onboarding, editable here since not every student sets it up front.
  const [category, setCategory] = useState("General");
  const [preferredBranches, setPreferredBranches] = useState("");
  const [preferredStates, setPreferredStates] = useState("");
  const [collegeTypePreference, setCollegeTypePreference] = useState("any");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prediction, setPrediction] = useState<PredictionResponse | null>(null);

  useEffect(() => {
    if (profile?.category) setCategory(profile.category);
  }, [profile?.category]);

  useEffect(() => {
    api.exams
      .getProfile(examCode)
      .then((p) => {
        setStatus(p.status);
        if (p.rank) setRank(String(p.rank));
        if (p.percentile) setPercentile(String(p.percentile));
        if (p.preferred_branches?.length) setPreferredBranches(p.preferred_branches.join(", "));
        if (p.preferred_states?.length) setPreferredStates(p.preferred_states.join(", "));
        if (p.college_type_preference) setCollegeTypePreference(p.college_type_preference);
      })
      .catch(() => {
        /* no existing profile yet — start blank */
      });
  }, [examCode]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const branches = preferredBranches.split(",").map((s) => s.trim()).filter(Boolean);
    const states = preferredStates.split(",").map((s) => s.trim()).filter(Boolean);

    setSaving(true);
    try {
      if (category !== profile?.category) {
        await api.student.updateProfile({ category });
        await refreshProfile();
      }
      await api.exams.saveProfile({
        exam_code: examCode,
        status,
        rank: rank ? Number(rank) : undefined,
        percentile: percentile ? Number(percentile) : undefined,
        preferred_branches: branches,
        preferred_states: states,
        college_type_preference: collegeTypePreference,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your exam profile.");
      setSaving(false);
      return;
    }
    setSaving(false);

    if (!rank) return; // nothing to predict against yet

    setLoading(true);
    try {
      const result = await predict({
        exam_code: examCode,
        rank: Number(rank),
        category,
        preferred_branches: branches,
        preferred_states: states,
        college_type_preference: collegeTypePreference,
      });
      setPrediction(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not generate a prediction right now.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <form onSubmit={handleSubmit} className="grid sm:grid-cols-2 gap-4">
          <div>
            <Label>Status</Label>
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
          </div>
          <div>
            <Label>Category</Label>
            <Select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
          </div>
          <div>
            <Label>{examLabel} rank</Label>
            <Input type="number" min={1} value={rank} onChange={(e) => setRank(e.target.value)} placeholder="e.g. 45000" />
          </div>
          <div>
            <Label>Percentile (optional)</Label>
            <Input type="number" step="0.01" min={0} max={100} value={percentile} onChange={(e) => setPercentile(e.target.value)} />
          </div>
          <div>
            <Label>Preferred branches (comma-separated, optional)</Label>
            <Input value={preferredBranches} onChange={(e) => setPreferredBranches(e.target.value)} placeholder="e.g. Computer Science, Electronics" />
          </div>
          <div>
            <Label>Preferred states (comma-separated, optional)</Label>
            <Input value={preferredStates} onChange={(e) => setPreferredStates(e.target.value)} placeholder="e.g. Maharashtra, Telangana" />
          </div>
          <div>
            <Label>College type</Label>
            <Select value={collegeTypePreference} onChange={(e) => setCollegeTypePreference(e.target.value)}>
              <option value="any">Any</option>
              <option value="government">Government</option>
              <option value="private">Private</option>
            </Select>
          </div>
          <div className="sm:col-span-2">
            <ErrorMessage message={error} />
            <Button type="submit" disabled={saving || loading}>
              {saving ? "Saving…" : loading ? "Predicting…" : rank ? "Save & Predict Colleges" : "Save Exam Profile"}
            </Button>
          </div>
        </form>
      </Card>

      {prediction && <PredictionResults prediction={prediction} />}
    </div>
  );
}

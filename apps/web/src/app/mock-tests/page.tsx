"use client";

import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { api, ApiError, Exam, MockTest, MockTestDashboard } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Button, Card, ErrorMessage, Input, Label, PageHeading, Select, Spinner } from "@/components/ui";

const SUBJECTS_BY_EXAM: Record<string, string[]> = {
  JEE_MAIN: ["Physics", "Chemistry", "Maths"],
  JEE_ADVANCED: ["Physics", "Chemistry", "Maths"],
  NEET_UG: ["Physics", "Chemistry", "Biology"],
};

function trendColor(trend: string) {
  if (trend === "Improving") return "text-chance-high-fg";
  if (trend === "Needs improvement") return "text-chance-ambitious-fg";
  return "text-muted";
}

function MockTestsContent() {
  const [exams, setExams] = useState<Exam[]>([]);
  const [examCode, setExamCode] = useState<string>("");
  const [dashboard, setDashboard] = useState<MockTestDashboard | null>(null);
  const [history, setHistory] = useState<MockTest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formExamCode, setFormExamCode] = useState("JEE_MAIN");
  const [testName, setTestName] = useState("");
  const [testDate, setTestDate] = useState(new Date().toISOString().slice(0, 10));
  const [maxScore, setMaxScore] = useState("300");
  const [subjectMarks, setSubjectMarks] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.exams.list().then(setExams).catch(() => {});
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [d, h] = await Promise.all([
        api.mockTests.dashboard(examCode || undefined),
        api.mockTests.history(examCode || undefined),
      ]);
      setDashboard(d);
      setHistory(h);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load mock test data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examCode]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const subjects = SUBJECTS_BY_EXAM[formExamCode] ?? [];
    const scores: Record<string, number> = {};
    let total = 0;
    for (const s of subjects) {
      const v = Number(subjectMarks[s] || 0);
      scores[s.toLowerCase()] = v;
      total += v;
    }
    setSaving(true);
    try {
      await api.mockTests.create({
        exam_code: formExamCode,
        test_name: testName,
        test_date: testDate,
        total_score: total,
        max_score: Number(maxScore),
        subject_scores: scores,
      });
      setTestName("");
      setSubjectMarks({});
      await loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save this mock test.");
    } finally {
      setSaving(false);
    }
  }

  const subjects = SUBJECTS_BY_EXAM[formExamCode] ?? [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title="Mock Test Tracking" subtitle="Log your mock scores to see trends and get an estimated rank range." />

      <div className="flex gap-2">
        <Select value={examCode} onChange={(e) => setExamCode(e.target.value)} className="max-w-xs">
          <option value="">All exams</option>
          {exams.map((ex) => <option key={ex.code} value={ex.code}>{ex.name}</option>)}
        </Select>
      </div>

      <ErrorMessage message={error} />

      <Card>
        <h3 className="font-semibold mb-4">Log a new mock test</h3>
        <form onSubmit={handleAdd} className="grid sm:grid-cols-2 gap-4">
          <div>
            <Label>Exam</Label>
            <Select value={formExamCode} onChange={(e) => { setFormExamCode(e.target.value); setSubjectMarks({}); }}>
              {Object.keys(SUBJECTS_BY_EXAM).map((code) => <option key={code} value={code}>{code.replace("_", " ")}</option>)}
            </Select>
          </div>
          <div>
            <Label>Test name</Label>
            <Input required value={testName} onChange={(e) => setTestName(e.target.value)} placeholder="e.g. Allen Mock Test 4" />
          </div>
          <div>
            <Label>Date</Label>
            <Input required type="date" value={testDate} onChange={(e) => setTestDate(e.target.value)} />
          </div>
          <div>
            <Label>Max score</Label>
            <Input required type="number" value={maxScore} onChange={(e) => setMaxScore(e.target.value)} />
          </div>
          {subjects.map((s) => (
            <div key={s}>
              <Label>{s} marks</Label>
              <Input
                type="number"
                value={subjectMarks[s] ?? ""}
                onChange={(e) => setSubjectMarks((prev) => ({ ...prev, [s]: e.target.value }))}
              />
            </div>
          ))}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={saving}>{saving ? "Saving…" : "Add Mock Test"}</Button>
          </div>
        </form>
      </Card>

      {loading ? (
        <Spinner />
      ) : dashboard && dashboard.test_count > 0 ? (
        <>
          <div className="grid sm:grid-cols-4 gap-4">
            <Card><p className="text-xs text-muted">Average</p><p className="text-xl font-bold">{dashboard.average_score_pct}%</p></Card>
            <Card><p className="text-xs text-muted">Best</p><p className="text-xl font-bold">{dashboard.best_score_pct}%</p></Card>
            <Card><p className="text-xs text-muted">Lowest</p><p className="text-xl font-bold">{dashboard.lowest_score_pct}%</p></Card>
            <Card><p className="text-xs text-muted">Recent avg (last 3)</p><p className="text-xl font-bold">{dashboard.recent_average_pct}%</p></Card>
          </div>

          <Card>
            <h3 className="font-semibold mb-4">Score trend</h3>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={dashboard.trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--card-border)" />
                <XAxis dataKey="test_name" tick={{ fontSize: 11 }} hide={dashboard.trend.length > 6} />
                <YAxis tick={{ fontSize: 11 }} domain={[0, 100]} />
                <Tooltip />
                <Line type="monotone" dataKey="score_pct" stroke="var(--primary)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </Card>

          <div className="grid md:grid-cols-2 gap-4">
            <Card>
              <h3 className="font-semibold mb-3">Subject-wise trend</h3>
              <ul className="flex flex-col gap-2 text-sm">
                {dashboard.subject_trends.map((s) => (
                  <li key={s.subject} className="flex justify-between">
                    <span className="capitalize">{s.subject}</span>
                    <span className={trendColor(s.trend)}>{s.trend} (avg {s.average})</span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <h3 className="font-semibold mb-3">Strengths & weak areas</h3>
              <p className="text-sm mb-2"><span className="text-chance-high-fg font-medium">Strong: </span>{dashboard.strong_subjects.join(", ") || "Not enough data yet"}</p>
              <p className="text-sm mb-2"><span className="text-chance-ambitious-fg font-medium">Needs work: </span>{dashboard.weak_subjects.join(", ") || "None flagged yet"}</p>
              {dashboard.estimated_rank_range && (
                <p className="text-sm text-muted mt-3">Estimated rank range: {dashboard.estimated_rank_range}</p>
              )}
              <p className="text-xs text-muted mt-2">{dashboard.estimate_disclaimer}</p>
            </Card>
          </div>

          <Card>
            <h3 className="font-semibold mb-3">History</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-muted text-left">
                  <tr><th className="py-1 pr-4">Test</th><th className="py-1 pr-4">Date</th><th className="py-1 pr-4">Score</th></tr>
                </thead>
                <tbody>
                  {history.map((t) => (
                    <tr key={t.id} className="border-t border-card-border">
                      <td className="py-1 pr-4">{t.test_name}</td>
                      <td className="py-1 pr-4">{t.test_date}</td>
                      <td className="py-1 pr-4">{t.total_score} / {t.max_score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      ) : (
        <Card><p className="text-muted text-sm">No mock tests logged yet — add your first one above.</p></Card>
      )}
    </div>
  );
}

export default function MockTestsPage() {
  return (
    <ProtectedRoute>
      <MockTestsContent />
    </ProtectedRoute>
  );
}

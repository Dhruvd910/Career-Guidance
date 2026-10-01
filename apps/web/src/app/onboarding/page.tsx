"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { api, ApiError, NextOnboardingStep } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Button, Card, ErrorMessage, Input, Label, PageHeading, Select, Spinner } from "@/components/ui";

function OnboardingFlow() {
  const { profile, refreshProfile } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<NextOnboardingStep | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [state, setState] = useState("");
  const [domicileState, setDomicileState] = useState("");
  const [board, setBoard] = useState("CBSE");
  const [category, setCategory] = useState("General");

  async function loadStep() {
    setLoading(true);
    try {
      const s = await api.student.nextOnboardingStep();
      setStep(s);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load onboarding step.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStep();
  }, []);

  async function submitBasicInfo(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.student.updateProfile({
        state,
        domicile_state: domicileState || state,
        school_board: board,
        category,
      });
      await loadStep();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your details.");
    }
  }

  async function answerKnowsCareerGoal(knows: boolean) {
    setError(null);
    try {
      await api.student.updateProfile({ knows_career_goal: knows });
      await loadStep();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your answer.");
    }
  }

  async function finishOnboarding(nextPath: string) {
    try {
      await api.student.updateProfile({ onboarding_completed: true });
      await refreshProfile();
    } finally {
      router.push(nextPath);
    }
  }

  if (loading) return <Spinner />;

  return (
    <div className="max-w-lg mx-auto">
      <PageHeading title={`Hi ${profile?.name?.split(" ")[0] ?? ""}, let's get started`} subtitle={step?.prompt} />
      <ErrorMessage message={error} />

      {step?.step === "basic_info" && (
        <Card>
          <form onSubmit={submitBasicInfo} className="flex flex-col gap-4">
            <div>
              <Label>Which state do you live in?</Label>
              <Input required value={state} onChange={(e) => setState(e.target.value)} placeholder="e.g. Maharashtra" />
            </div>
            <div>
              <Label>Domicile state (for admission quota, if different)</Label>
              <Input value={domicileState} onChange={(e) => setDomicileState(e.target.value)} placeholder="Same as above if blank" />
            </div>
            <div>
              <Label>School board</Label>
              <Select value={board} onChange={(e) => setBoard(e.target.value)}>
                {["CBSE", "ICSE", "State Board", "Other"].map((b) => <option key={b} value={b}>{b}</option>)}
              </Select>
            </div>
            <div>
              <Label>Category (only used where relevant for admission prediction)</Label>
              <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                {["General", "EWS", "OBC", "SC", "ST", "Other"].map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </div>
            <Button type="submit">Continue</Button>
          </form>
        </Card>
      )}

      {step?.step === "career_exploration_assessment" && (
        <Card className="text-center">
          <p className="text-muted mb-4">
            We&apos;ll ask about your interests, favorite subjects, and the kind of work you imagine enjoying —
            no pressure to decide anything yet.
          </p>
          <Button onClick={() => finishOnboarding("/careers?type=class8_9_exploration")}>Start Exploration</Button>
        </Card>
      )}

      {step?.step === "stream_assessment" && (
        <Card className="text-center">
          <p className="text-muted mb-4">A short set of questions to recommend PCM, PCB, Commerce, or Arts.</p>
          <Button onClick={() => finishOnboarding("/careers?type=class10_stream")}>Start Stream Assessment</Button>
        </Card>
      )}

      {step?.step === "career_goal_question" && (
        <Card className="flex flex-col items-center gap-4">
          <p className="text-muted">{step.prompt}</p>
          <div className="flex gap-3">
            <Button onClick={() => answerKnowsCareerGoal(true)}>Yes, I know</Button>
            <Button variant="secondary" onClick={() => answerKnowsCareerGoal(false)}>Not sure yet</Button>
          </div>
        </Card>
      )}

      {step?.step === "exam_selection" && (
        <Card className="flex flex-col gap-3">
          <Button onClick={() => finishOnboarding("/exams/jee")}>JEE (Engineering)</Button>
          <Button onClick={() => finishOnboarding("/exams/neet")}>NEET (Medical)</Button>
          <Button variant="secondary" onClick={() => finishOnboarding("/careers")}>Something else</Button>
        </Card>
      )}

      {step?.step === "career_counselling_assessment" && (
        <Card className="text-center">
          <p className="text-muted mb-4">
            Let&apos;s run a structured conversation about your strengths, interests, and goals to find
            career paths that may fit — engineering, medicine, law, design, commerce, and more.
          </p>
          <Button onClick={() => finishOnboarding("/careers?type=class11_12_career")}>Start Career Counselling</Button>
        </Card>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <ProtectedRoute>
      <OnboardingFlow />
    </ProtectedRoute>
  );
}

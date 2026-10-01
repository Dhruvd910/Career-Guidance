"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { api, RoadmapResponse } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Card, LinkButton, PageHeading, Spinner } from "@/components/ui";

function DashboardContent() {
  const { profile } = useAuth();
  const router = useRouter();
  const [roadmap, setRoadmap] = useState<RoadmapResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (profile && !profile.onboarding_completed) {
      router.replace("/onboarding");
    }
  }, [profile, router]);

  useEffect(() => {
    api.roadmap.get().then(setRoadmap).finally(() => setLoading(false));
  }, []);

  if (!profile || loading) return <Spinner />;

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={`Welcome back, ${profile.name.split(" ")[0]}`} subtitle={`Class ${profile.class_level} · ${profile.state ?? "Location not set"}`} />

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <h3 className="font-semibold mb-2">Your Roadmap</h3>
          {roadmap ? (
            <>
              <p className="text-sm text-muted mb-1">Current milestone</p>
              <p className="font-medium mb-3">{roadmap.current_milestone}</p>
              <p className="text-sm text-muted mb-1">Next action</p>
              <p className="mb-4">{roadmap.next_action}</p>
            </>
          ) : (
            <p className="text-muted text-sm mb-4">Roadmap unavailable right now.</p>
          )}
          <LinkButton href="/roadmap" variant="secondary">View full roadmap</LinkButton>
        </Card>

        <Card>
          <h3 className="font-semibold mb-2">AI Career Counsellor</h3>
          <p className="text-sm text-muted mb-4">
            Ask about your options, get college comparisons, or talk through a decision — by text or voice.
          </p>
          <LinkButton href="/chat">Open AI Assistant</LinkButton>
        </Card>
      </div>

      <div className="grid sm:grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <h4 className="font-semibold mb-2">Careers</h4>
          <p className="text-sm text-muted mb-3">Explore fits and run an assessment.</p>
          <LinkButton href="/careers" variant="secondary">Explore</LinkButton>
        </Card>
        <Card>
          <h4 className="font-semibold mb-2">Exams</h4>
          <p className="text-sm text-muted mb-3">JEE / NEET profile & prediction.</p>
          <LinkButton href="/exams/jee" variant="secondary">JEE</LinkButton>
        </Card>
        <Card>
          <h4 className="font-semibold mb-2">Mock Tests</h4>
          <p className="text-sm text-muted mb-3">Track scores and trends.</p>
          <LinkButton href="/mock-tests" variant="secondary">View</LinkButton>
        </Card>
        <Card>
          <h4 className="font-semibold mb-2">Colleges</h4>
          <p className="text-sm text-muted mb-3">Discover and compare colleges.</p>
          <LinkButton href="/colleges" variant="secondary">Browse</LinkButton>
        </Card>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <ProtectedRoute>
      <DashboardContent />
    </ProtectedRoute>
  );
}

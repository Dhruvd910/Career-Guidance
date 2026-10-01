"use client";

import { useEffect, useState } from "react";
import { api, ApiError, RoadmapResponse } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Card, ErrorMessage, PageHeading, Spinner } from "@/components/ui";

function RoadmapContent() {
  const [roadmap, setRoadmap] = useState<RoadmapResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.roadmap.get().then(setRoadmap).catch((err) => setError(err instanceof ApiError ? err.message : "Could not load your roadmap."));
  }, []);

  if (error) return <ErrorMessage message={error} />;
  if (!roadmap) return <Spinner />;

  const statusStyle: Record<string, string> = {
    done: "bg-chance-high-bg text-chance-high-fg border-transparent",
    current: "border-primary text-primary",
    upcoming: "border-card-border text-muted",
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title="My Career Roadmap" subtitle={roadmap.long_term_goal} />
      <div className="flex flex-col gap-3">
        {roadmap.steps.map((step) => (
          <Card key={step.order} className={`border-2 ${statusStyle[step.status]}`}>
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{step.order}. {step.title}</h3>
              <span className="text-xs uppercase font-bold">{step.status}</span>
            </div>
            <p className="text-sm text-muted mt-1">{step.description}</p>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function RoadmapPage() {
  return (
    <ProtectedRoute>
      <RoadmapContent />
    </ProtectedRoute>
  );
}

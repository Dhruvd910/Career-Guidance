"use client";

import { api } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ExamPredictorForm } from "@/components/ExamPredictorForm";
import { PageHeading } from "@/components/ui";

export default function NeetPage() {
  return (
    <ProtectedRoute>
      <PageHeading
        title="NEET-UG Guidance & College Prediction"
        subtitle="Enter your rank to get explainable, data-driven MBBS/BDS college predictions."
      />
      <ExamPredictorForm examCode="NEET_UG" examLabel="NEET-UG" predict={api.predictions.predictNeet} />
    </ProtectedRoute>
  );
}

"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { ExamPredictorForm } from "@/components/ExamPredictorForm";
import { PageHeading } from "@/components/ui";

export default function JeePage() {
  const [examCode, setExamCode] = useState<"JEE_MAIN" | "JEE_ADVANCED">("JEE_MAIN");

  return (
    <ProtectedRoute>
      <PageHeading
        title="JEE Guidance & College Prediction"
        subtitle="Enter your rank to get explainable, data-driven college and branch predictions."
      />
      <div className="flex gap-2 mb-6">
        {(["JEE_MAIN", "JEE_ADVANCED"] as const).map((code) => (
          <button
            key={code}
            onClick={() => setExamCode(code)}
            className={`px-4 py-2 rounded-lg text-sm font-medium ${examCode === code ? "bg-primary text-primary-foreground" : "bg-card border border-card-border"}`}
          >
            {code === "JEE_MAIN" ? "JEE Main" : "JEE Advanced"}
          </button>
        ))}
      </div>
      <ExamPredictorForm
        key={examCode}
        examCode={examCode}
        examLabel={examCode === "JEE_MAIN" ? "JEE Main" : "JEE Advanced"}
        predict={api.predictions.predictJee}
      />
    </ProtectedRoute>
  );
}

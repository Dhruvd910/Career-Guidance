"use client";

import { useAuth } from "@/lib/auth-context";
import { LinkButton, Card } from "@/components/ui";

const PILLARS = [
  { title: "What can I become?", desc: "Explore career families that fit your interests, strengths, and personality — not a forced choice." },
  { title: "What can I realistically get?", desc: "Data-driven, explainable JEE/NEET rank and college predictions based on historical cutoffs." },
  { title: "What should I do next?", desc: "A personalized, step-by-step roadmap from where you are today to your goal." },
];

export default function LandingPage() {
  const { isAuthenticated } = useAuth();

  return (
    <div className="flex flex-col gap-16 py-8">
      <section className="text-center flex flex-col items-center gap-5">
        <span className="demo-badge">DEMO DATA — sample college dataset for development</span>
        <h1 className="text-4xl font-bold max-w-2xl">
          Figure out your career, exam, and college path — with data, not guesswork.
        </h1>
        <p className="text-muted max-w-xl">
          For Class 8–12 students preparing for JEE, NEET, or still deciding. Honest predictions,
          real explanations, and a counsellor that never guarantees an outcome it can&apos;t back up.
        </p>
        <LinkButton href={isAuthenticated ? "/dashboard" : "/register"}>
          {isAuthenticated ? "Go to Dashboard" : "Start Your Career Journey"}
        </LinkButton>
      </section>

      <section className="grid md:grid-cols-3 gap-4">
        {PILLARS.map((p) => (
          <Card key={p.title}>
            <h3 className="font-semibold mb-2">{p.title}</h3>
            <p className="text-sm text-muted">{p.desc}</p>
          </Card>
        ))}
      </section>

      <section className="text-center text-sm text-muted">
        <p>
          Predictions are probability estimates from historical data — never a guarantee of admission.
          Every fact shown links back to its source and last-verified date.
        </p>
      </section>
    </div>
  );
}

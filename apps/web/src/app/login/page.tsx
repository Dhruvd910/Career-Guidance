"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { Button, Card, ErrorMessage, Input, Label, PageHeading } from "@/components/ui";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-md mx-auto">
      <PageHeading title="Welcome back" />
      <Card>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <Label>Email</Label>
            <Input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <Label>Password</Label>
            <Input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <ErrorMessage message={error} />
          <Button type="submit" disabled={submitting}>{submitting ? "Logging in…" : "Log in"}</Button>
        </form>
      </Card>
      <p className="text-sm text-muted text-center mt-4">
        New here? <a href="/register" className="text-primary">Create an account</a>
      </p>
    </div>
  );
}

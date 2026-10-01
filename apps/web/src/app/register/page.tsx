"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { Button, Card, ErrorMessage, Input, Label, PageHeading, Select } from "@/components/ui";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [classLevel, setClassLevel] = useState(11);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register(email, password, name, classLevel);
      router.push("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-md mx-auto">
      <PageHeading title="Create your account" subtitle="Takes less than a minute." />
      <Card>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <Label>Full name</Label>
            <Input required value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <Label>Email</Label>
            <Input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <Label>Password (min 8 characters)</Label>
            <Input required type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div>
            <Label>Current class</Label>
            <Select value={classLevel} onChange={(e) => setClassLevel(Number(e.target.value))}>
              {[8, 9, 10, 11, 12].map((c) => (
                <option key={c} value={c}>Class {c}</option>
              ))}
            </Select>
          </div>
          <ErrorMessage message={error} />
          <Button type="submit" disabled={submitting}>{submitting ? "Creating account…" : "Create account"}</Button>
        </form>
      </Card>
      <p className="text-sm text-muted text-center mt-4">
        Already have an account? <a href="/login" className="text-primary">Log in</a>
      </p>
    </div>
  );
}

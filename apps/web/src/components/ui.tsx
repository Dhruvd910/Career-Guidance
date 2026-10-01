import Link from "next/link";
import { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`bg-card border border-card-border rounded-xl shadow-sm p-5 ${className}`}>
      {children}
    </div>
  );
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" }) {
  const base = "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-primary text-primary-foreground hover:opacity-90",
    secondary: "bg-card-border/60 text-foreground hover:bg-card-border",
    ghost: "text-primary hover:underline",
  };
  return <button className={`${base} ${styles[variant]} ${className}`} {...props} />;
}

export function LinkButton({ href, children, variant = "primary" }: { href: string; children: ReactNode; variant?: "primary" | "secondary" }) {
  const base = "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition";
  const styles = {
    primary: "bg-primary text-primary-foreground hover:opacity-90",
    secondary: "bg-card-border/60 text-foreground hover:bg-card-border",
  };
  return (
    <Link href={href} className={`${base} ${styles[variant]}`}>
      {children}
    </Link>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-lg border border-card-border bg-card px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary ${props.className ?? ""}`}
    />
  );
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={`w-full rounded-lg border border-card-border bg-card px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary ${props.className ?? ""}`}
    />
  );
}

export function Label({ children }: { children: ReactNode }) {
  return <label className="block text-sm font-medium mb-1 text-muted">{children}</label>;
}

export function PageHeading({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-bold">{title}</h1>
      {subtitle && <p className="text-muted mt-1">{subtitle}</p>}
    </div>
  );
}

export function Disclaimer({ children }: { children: ReactNode }) {
  return (
    <p className="text-xs text-muted border-l-2 border-card-border pl-3 py-1 mt-4">{children}</p>
  );
}

export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="error-banner">{message}</div>;
}

export function RangeSlider({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span>{label}</span>
        <span className="text-muted">{value}/10</span>
      </div>
      <input
        type="range"
        min={0}
        max={10}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-[var(--primary)]"
      />
    </div>
  );
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-10 text-muted text-sm">Loading…</div>
  );
}

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/careers", label: "Careers" },
  { href: "/colleges", label: "Colleges" },
  { href: "/mock-tests", label: "Mock Tests" },
  { href: "/roadmap", label: "Roadmap" },
  { href: "/chat", label: "AI Assistant" },
];

export function Navbar() {
  const { isAuthenticated, logout, profile } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  return (
    <header className="border-b border-card-border bg-card sticky top-0 z-10">
      <div className="max-w-6xl mx-auto flex items-center justify-between px-4 py-3">
        <Link href="/" className="font-bold text-lg text-primary">
          AI Career Guide
        </Link>
        {isAuthenticated && (
          <nav className="hidden md:flex items-center gap-5 text-sm">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={pathname === link.href ? "font-semibold text-primary" : "text-muted hover:text-foreground"}
              >
                {link.label}
              </Link>
            ))}
          </nav>
        )}
        <div className="flex items-center gap-3 text-sm">
          {isAuthenticated ? (
            <>
              <span className="text-muted hidden sm:inline">Hi, {profile?.name}</span>
              <button
                className="text-muted hover:text-foreground"
                onClick={() => {
                  logout();
                  router.push("/");
                }}
              >
                Log out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="text-muted hover:text-foreground">Log in</Link>
              <Link href="/register" className="bg-primary text-primary-foreground rounded-lg px-3 py-1.5 font-semibold">
                Get Started
              </Link>
            </>
          )}
        </div>
      </div>
      {isAuthenticated && (
        <nav className="md:hidden flex gap-4 px-4 pb-3 text-xs overflow-x-auto">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href} className={pathname === link.href ? "font-semibold text-primary whitespace-nowrap" : "text-muted whitespace-nowrap"}>
              {link.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

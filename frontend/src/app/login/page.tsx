"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Logo } from "@/components/finsight/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/components/finsight/auth-provider";
import { api, ApiError } from "@/lib/api";

function LoginInner() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (searchParams.get("reason") === "expired") {
      setError("Your session has expired. Please sign in again.");
    }
  }, [searchParams]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res =
        mode === "register"
          ? await api.register(email, password, name || undefined)
          : await api.login(email, password);
      login(res.access_token, res.user);
      router.replace("/home");
    } catch (err) {
      if (err instanceof ApiError) {
        const detail =
          typeof err.body === "object" && err.body && "detail" in err.body
            ? (err.body as { detail: string }).detail
            : err.message;
        setError(detail);
      } else {
        setError("Something went wrong");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--color-background)] px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <Logo size="lg" />
          <p className="mt-3 text-sm text-[var(--color-muted-strong)]">
            {mode === "login"
              ? "Sign in to your account"
              : "Create a new account"}
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "register" && (
            <div>
              <label className="mb-1 block text-xs text-[var(--color-muted)]">
                Name (optional)
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted)]">
              Email
            </label>
            <Input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-[var(--color-muted)]">
              Password
            </label>
            <Input
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "At least 6 characters" : ""}
            />
          </div>

          {error && (
            <div className="rounded-[var(--radius-md)] border border-[color:color-mix(in_oklab,var(--color-danger)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-danger)_10%,transparent)] p-3 text-xs text-[var(--color-danger)]">
              {error}
            </div>
          )}

          <Button
            type="submit"
            variant="primary"
            className="w-full"
            disabled={loading}
          >
            {loading
              ? "Please wait..."
              : mode === "login"
              ? "Sign in"
              : "Create account"}
          </Button>
        </form>

        <div className="mt-6 text-center text-sm text-[var(--color-muted)]">
          {mode === "login" ? (
            <>
              Don&apos;t have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("register");
                  setError(null);
                }}
                className="text-[var(--color-accent)] hover:underline"
              >
                Sign up
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setMode("login");
                  setError(null);
                }}
                className="text-[var(--color-accent)] hover:underline"
              >
                Sign in
              </button>
            </>
          )}
        </div>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}

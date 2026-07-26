/**
 * LoginPage — operator password gate for the ApexQuant AI dashboard.
 *
 * The operator enters the SESSION_SECRET value configured on the API server.
 * On success the server issues an HttpOnly session cookie; the browser sends
 * it automatically on all subsequent requests.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { buildApiUrl } from "@/lib/apiConfig";

interface LoginPageProps {
  /** Called after a successful login so the parent re-checks auth state. */
  onAuthenticated: () => void;
}

export function LoginPage({ onAuthenticated }: LoginPageProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const queryClient = useQueryClient();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const res = await fetch(buildApiUrl("/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
        credentials: "include",
      });

      if (res.ok) {
        // Invalidate the auth/me query so useAuth re-fetches with the new cookie
        await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
        onAuthenticated();
      } else {
        setError("Invalid credentials. Check your SESSION_SECRET value.");
      }
    } catch {
      setError("Could not reach the API server. Is it running?");
    } finally {
      setSubmitting(false);
      setPassword("");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-sm space-y-6 p-8 rounded-xl border border-border bg-card shadow-lg">
        {/* Brand */}
        <div className="text-center space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            ApexQuant AI
          </h1>
          <p className="text-sm text-muted-foreground">
            Operator access — enter your session secret
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label
              htmlFor="password"
              className="text-sm font-medium text-foreground"
            >
              Session secret
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              placeholder="Enter SESSION_SECRET"
              className={[
                "w-full rounded-md border px-3 py-2 text-sm",
                "bg-background text-foreground placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-ring",
                error ? "border-destructive" : "border-input",
              ].join(" ")}
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting || !password}
            className={[
              "w-full rounded-md px-4 py-2 text-sm font-medium transition-colors",
              "bg-primary text-primary-foreground",
              "hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed",
            ].join(" ")}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}

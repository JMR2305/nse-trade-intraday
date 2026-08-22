import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { isAdvisoryUiEnabled } from "@/lib/advisoryFlags";
import NotFound from "@/pages/not-found";

type AdvisoryStatus = {
  status?: string;
  manual_only?: boolean;
  scheduler_hook?: boolean;
  last_run_at?: string | null;
  flags?: Record<string, boolean>;
};

function StatusValue({ value }: { value: string }) {
  return (
    <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
      {value}
    </span>
  );
}

export default function AdvisoryDashboard() {
  const uiEnabled = isAdvisoryUiEnabled();
  const statusQuery = useQuery<AdvisoryStatus>({
    queryKey: ["/advisory/status"],
    queryFn: () => apiJson<AdvisoryStatus>("/advisory/status"),
    enabled: uiEnabled,
    staleTime: 30_000,
  });

  if (!uiEnabled) return <NotFound />;

  const data = statusQuery.data;
  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-6">
      <section className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-5">
        <p className="text-xs font-bold uppercase tracking-[0.18em] text-amber-300">
          Advisory integration
        </p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">
          Advisory Bot Dashboard
        </h1>
        <p className="mt-2 text-sm font-semibold text-amber-200">
          ADVISORY ONLY — NOT ORDER INSTRUCTIONS
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          This page is read-only. Runs are manual and no trading action can be
          taken here.
        </p>
      </section>

      {statusQuery.isLoading && (
        <section className="rounded-2xl border bg-card p-5 text-sm text-muted-foreground">
          Loading advisory status…
        </section>
      )}

      {statusQuery.isError && (
        <section className="rounded-2xl border border-destructive/30 bg-destructive/10 p-5 text-sm text-destructive">
          Advisory status is unavailable. The integration remains disabled or
          the optional API surface is not enabled.
        </section>
      )}

      <section className="grid gap-4 md:grid-cols-3">
        <article className="rounded-2xl border bg-card p-5">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">
            Feature status
          </p>
          <div className="mt-3">
            <StatusValue value={data?.status ?? "UNAVAILABLE"} />
          </div>
        </article>
        <article className="rounded-2xl border bg-card p-5">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">
            Last manual run
          </p>
          <p className="mt-3 text-sm font-semibold">
            {data?.last_run_at ?? "No manual run recorded"}
          </p>
        </article>
        <article className="rounded-2xl border bg-card p-5">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">
            Scheduler
          </p>
          <p className="mt-3 text-sm font-semibold">
            {data?.scheduler_hook === false ? "Not connected" : "Unavailable"}
          </p>
        </article>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <article className="rounded-2xl border bg-card p-5">
          <h2 className="font-semibold">Read-only evidence panels</h2>
          <div className="mt-4 grid gap-3 text-sm text-muted-foreground sm:grid-cols-2">
            <div className="rounded-xl bg-muted/40 p-3">Universe health: awaiting manual run</div>
            <div className="rounded-xl bg-muted/40 p-3">Data quality: awaiting manual run</div>
            <div className="rounded-xl bg-muted/40 p-3">Top candidates: awaiting manual run</div>
            <div className="rounded-xl bg-muted/40 p-3">Strategy scores: awaiting manual run</div>
            <div className="rounded-xl bg-muted/40 p-3">Risk flags: awaiting manual run</div>
            <div className="rounded-xl bg-muted/40 p-3">Supervisor verdict: awaiting manual run</div>
          </div>
        </article>
        <article className="rounded-2xl border border-primary/20 bg-primary/5 p-5">
          <h2 className="font-semibold">Safety boundary</h2>
          <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
            <li>• No trade, position, or broker actions</li>
            <li>• No settings mutation</li>
            <li>• No scheduler control</li>
            <li>• No automatic entry or bootstrap path</li>
            <li>• Manual, advisory-only review only</li>
          </ul>
        </article>
      </section>
    </main>
  );
}
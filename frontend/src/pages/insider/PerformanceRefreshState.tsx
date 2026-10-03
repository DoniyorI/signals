import { Link } from "react-router";
import { EmptyState } from "@/components/state/EmptyState";
import type { useInsiderPerformanceRefresh } from "@/hooks/useInsiderPerformanceRefresh";

type Refresh = ReturnType<typeof useInsiderPerformanceRefresh>;

/** A profile's worker request is the source of its progress, independent of global history. */
export function PerformanceRefreshState({ refresh }: { refresh: Refresh }) {
  const healthLink = <Link to="/health" className="text-sm text-link hover:underline">Data health</Link>;
  if (refresh.requestError || refresh.statusError) {
    return <EmptyState reason="error" title={refresh.requestError ? "Performance refresh couldn't start" : "Performance refresh status didn't load"}
      description={(refresh.requestError ?? refresh.statusError)?.message} action={healthLink} />;
  }
  if (refresh.job?.status === "failed" || refresh.job?.status === "error") {
    return <EmptyState reason="error" title="Performance refresh needs attention"
      description={refresh.job.error ?? "The worker couldn't prepare this profile's performance."} action={healthLink} />;
  }
  if (refresh.isStarting || refresh.isRefreshing) {
    return <EmptyState reason="loading" title={refresh.isRefreshing ? "Updating performance…" : "Preparing this profile’s performance…"}
      description="Preparing this profile's prices and returns." action={healthLink} />;
  }
  const progress = refresh.job?.progress;
  if (refresh.job?.status === "running") {
    const calculating = progress?.stage === "analytics";
    const total = typeof progress?.symbols_total === "number" && Number.isFinite(progress.symbols_total) ? progress.symbols_total : null;
    const done = typeof progress?.symbols_done === "number" && Number.isFinite(progress.symbols_done) ? progress.symbols_done : 0;
    const missing = Array.isArray(progress?.missing) ? progress.missing.filter((symbol) => typeof symbol === "string").length : 0;
    const percent = total !== null && total > 0 ? Math.round(Math.max(0, Math.min(100, done / total * 100))) : undefined;
    return <EmptyState reason="loading" title={calculating ? "Calculating this profile’s performance" : "Loading this profile’s prices"}
      description={calculating ? "Calculating returns and ratings from this profile's available prices." :
        total !== null ? `${done} of ${total} symbols checked.` : "Loading the prices needed for this profile."}
      action={<>
        {missing > 0 && <p className="max-w-sm text-sm text-muted-foreground">
          {missing === 1 ? "1 symbol has" : `${missing} symbols have`} no price data available.
        </p>}
        {!calculating && percent !== undefined && <div role="progressbar" aria-label="This profile's price checks"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} className="h-2 w-48 overflow-hidden rounded bg-muted">
          <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
        </div>}
        {healthLink}
      </>} />;
  }
  return <EmptyState reason="loading" title="Performance refresh is queued"
    description="Waiting for the worker to prepare this profile's prices and returns." action={healthLink} />;
}

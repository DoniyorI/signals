import { Link } from "react-router";
import { useCoverage } from "@/hooks/useCoverage";
import { usePriceLoadStatus } from "@/hooks/usePriceLoadStatus";
import { EmptyState } from "./EmptyState";

/** Diagnose only from known evidence. A direct unmapped/absent security wins over global
 * loading, and callers with genuine filter misses should keep their filter explanation. */
export function CoverageEmptyState({
  title = "No performance data yet",
  notCovered = false,
  allowLoading = false,
  symbols = [],
  completedTrades,
  noPricesWhenIdle = false,
}: {
  title?: string;
  notCovered?: boolean;
  allowLoading?: boolean;
  symbols?: string[];
  completedTrades?: number | null;
  noPricesWhenIdle?: boolean;
}) {
  const coverage = useCoverage(!notCovered);
  const missingPrices = symbols.some((symbol) => coverage.data?.prices.missing_symbols.includes(symbol));
  const needsPriceContext = allowLoading || missingPrices || noPricesWhenIdle;
  const priceStatus = usePriceLoadStatus(!notCovered && coverage.isSuccess && needsPriceContext);
  if (notCovered) return <EmptyState reason="not_covered" />;
  if (coverage.isPending) return <EmptyState title="Checking data coverage…" />;
  if (coverage.isError) return <EmptyState reason="error" title="Coverage details didn't load"
    action={<button type="button" className="text-sm text-link hover:underline" onClick={() => { void coverage.refetch(); }}>Try again</button>} />;

  const prices = coverage.data.prices;
  const healthLink = <Link to="/health" className="text-sm text-link hover:underline">Data health</Link>;
  if (needsPriceContext && priceStatus.state === "failed") {
    return <EmptyState reason="error" title="Price loading needs attention" description={priceStatus.explanation} action={healthLink} />;
  }
  if (prices.loading && (allowLoading || missingPrices)) {
    const statusExplanation = priceStatus.isError ? "The price job status couldn't be read. Check Data health or try again." :
      priceStatus.explanation ?? (priceStatus.state === "unknown" ? "Price work is queued or running. Check Data health for current progress." : undefined);
    return <EmptyState reason="loading" title={priceStatus.state === "running" ? undefined : "Performance is waiting for prices"}
      percent={prices.pct == null ? null : prices.pct * 100}
      action={<>{statusExplanation && <p className="max-w-sm text-sm text-muted-foreground">{statusExplanation}</p>}{healthLink}</>} />;
  }
  if (noPricesWhenIdle && !prices.loading) return <EmptyState reason="not_covered" />;
  if (completedTrades != null && completedTrades < 3) {
    return <EmptyState reason="insufficient" completedTrades={completedTrades} />;
  }
  return <EmptyState title={title}
    description="The available data doesn't include calculated performance yet. Check Data health for coverage."
    action={<Link to="/health" className="text-sm text-link hover:underline">Data health</Link>} />;
}

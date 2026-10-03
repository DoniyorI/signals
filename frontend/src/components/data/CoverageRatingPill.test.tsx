import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { expect, it } from "vitest";
import { health } from "@/mocks/data/health";
import { server } from "@/mocks/node";
import { coverageFixture } from "@/test/coverage";
import { CoverageRatingPill } from "./CoverageRatingPill";

it("shows queued price work in missing ratings without suggesting a running price job", async () => {
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading: true, pct: 0 }))),
    http.get("/api/health", () => HttpResponse.json({ ...health(), jobs: [], backfill: [
      { step: "backfill_funds", status: "running", done_units: 12, total_units: 44, updated_at: null },
      { step: "backfill_prices", status: "pending", done_units: 0, total_units: null, updated_at: null },
    ] })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CoverageRatingPill rating={{ score: null, confidence: null, n: 0 }} /></QueryClientProvider>);
  expect(await screen.findByText("Price loading is queued (0% covered). Rating appears after returns are calculated.")).toBeInTheDocument();
});

it("explains a failed price job in a missing rating", async () => {
  server.use(
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ pct: 0 }))),
    http.get("/api/health", () => HttpResponse.json({ ...health(), jobs: [], backfill: [
      { step: "backfill_prices", status: "failed", done_units: 0, total_units: null, updated_at: null },
    ] })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><CoverageRatingPill rating={{ score: null, confidence: null, n: 0 }} /></QueryClientProvider>);
  expect(await screen.findByText("Price loading needs attention. Check Data health for details.")).toBeInTheDocument();
});

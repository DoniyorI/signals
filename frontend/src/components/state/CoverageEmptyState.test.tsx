import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";
import type { Schema } from "@/api/client";
import { health } from "@/mocks/data/health";
import { server } from "@/mocks/node";
import { coverageFixture } from "@/test/coverage";
import { CoverageEmptyState } from "./CoverageEmptyState";

function show(overrides: Partial<Schema<"HealthOut">>, { loading = true, noPricesWhenIdle = false } = {}) {
  server.use(
    http.get("/api/health", () => HttpResponse.json({ ...health(), ...overrides })),
    http.get("/api/health/completeness", () => HttpResponse.json(coverageFixture({ loading, pct: 0 }))),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><CoverageEmptyState allowLoading noPricesWhenIdle={noPricesWhenIdle} /></MemoryRouter></QueryClientProvider>);
  return client;
}

it("explains prices queued behind fund ingestion instead of claiming they are actively loading", async () => {
  show({ backfill: [
    { step: "backfill_funds", status: "running", done_units: 12, total_units: 44, updated_at: null },
    { step: "backfill_prices", status: "pending", done_units: 0, total_units: null, updated_at: null },
  ], jobs: [] });
  expect(await screen.findByText("Price loading is queued while fund filings finish.")).toBeInTheDocument();
  expect(screen.getByText("Performance is waiting for prices")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Data health" })).toHaveAttribute("href", "/health");
});

it("keeps the active price-loading explanation and provides a progress link", async () => {
  show({ backfill: [{ step: "backfill_prices", status: "running", done_units: 0, total_units: null, updated_at: null }], jobs: [] });
  expect(await screen.findByText("Performance is loading")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Data health" })).toHaveAttribute("href", "/health");
  expect(screen.getByText("Performance appears when prices finish loading (0% done).")).toBeInTheDocument();
  expect(screen.queryByText(/Price loading is queued/)).not.toBeInTheDocument();
});

it("shows a failed prerequisite even when completeness still indicates pending price work", async () => {
  show({ backfill: [
    { step: "backfill_funds", status: "failed", done_units: 12, total_units: 44, updated_at: null },
    { step: "backfill_prices", status: "pending", done_units: 0, total_units: null, updated_at: null },
  ], jobs: [] });
  expect(await screen.findByText("The historical backfill needs attention before prices can load.")).toBeInTheDocument();
  expect(screen.getByText("Price loading needs attention")).toBeInTheDocument();
  expect(screen.queryByText(/Performance appears when prices finish loading/)).not.toBeInTheDocument();
});

it("does not describe a failed price job as missing security coverage", async () => {
  show({ backfill: [{ step: "backfill_prices", status: "failed", done_units: 0, total_units: null, updated_at: null }], jobs: [] },
    { loading: false, noPricesWhenIdle: true });
  expect(await screen.findByText("Price loading failed. Check Data health for the error and retry status.")).toBeInTheDocument();
  expect(screen.queryByText("No price data for this security.")).not.toBeInTheDocument();
});

it.each([
  ["2026-10-02T19:00:00-04:00", "2026-10-02T23:30:00Z"],
  ["2026-10-02T23:00:00Z", "2026-10-02T19:30:00-04:00"],
])("shows a price failure after a completed stage across offsets (%s, %s)", async (completedAt, failedAt) => {
  show({
    backfill: [{ step: "backfill_prices", status: "done", done_units: 10, total_units: 10, updated_at: completedAt }],
    jobs: [{ kind: "prices_daily", last_status: "failed", last_started_at: failedAt, last_finished_at: failedAt, last_error: "Provider error" }],
  }, { loading: false });
  expect(await screen.findByText("Price loading needs attention")).toBeInTheDocument();
  expect(screen.getByText("Price loading failed. Check Data health for the error and retry status.")).toBeInTheDocument();
});

it("does not revive an older price failure when the completed stage has a different offset", async () => {
  const client = show({
    backfill: [{ step: "backfill_prices", status: "done", done_units: 10, total_units: 10, updated_at: "2026-10-02T19:30:00-04:00" }],
    jobs: [{ kind: "prices_daily", last_status: "failed", last_started_at: "2026-10-02T22:50:00Z", last_finished_at: "2026-10-02T23:00:00Z", last_error: "Old error" }],
  }, { loading: false });
  await waitFor(() => expect(client.getQueryState(["health"])?.status).toBe("success"));
  expect(await screen.findByText("The available data doesn't include calculated performance yet. Check Data health for coverage.")).toBeInTheDocument();
  expect(screen.queryByText("Price loading needs attention")).not.toBeInTheDocument();
});

it("selects the most recent price job by instant across offsets", async () => {
  show({ backfill: [], jobs: [
    { kind: "backfill_prices", last_status: "done", last_started_at: "2026-10-02T22:00:00Z", last_finished_at: "2026-10-02T23:00:00Z", last_error: null },
    { kind: "prices_daily", last_status: "failed", last_started_at: "2026-10-02T19:15:00-04:00", last_finished_at: "2026-10-02T19:30:00-04:00", last_error: "Provider error" },
  ] }, { loading: false });
  expect(await screen.findByText("Price loading needs attention")).toBeInTheDocument();
});

it("shows a newer standalone price retry instead of an older failed prerequisite", async () => {
  show({ backfill: [
    { step: "backfill_funds", status: "failed", done_units: 12, total_units: 44, updated_at: "2026-10-02T23:00:00Z" },
    { step: "backfill_prices", status: "pending", done_units: 0, total_units: null, updated_at: "2026-10-02T22:00:00Z" },
  ], jobs: [
    { kind: "backfill_all", last_status: "failed", last_started_at: "2026-10-02T20:00:00Z", last_finished_at: "2026-10-02T23:00:00Z", last_error: "Fund error" },
    { kind: "backfill_prices", last_status: "queued", last_started_at: "2026-10-02T19:30:00-04:00", last_finished_at: null, last_error: null },
  ] });
  expect(await screen.findByText("Price loading is queued and has not started yet.")).toBeInTheDocument();
  expect(screen.queryByText("Price loading needs attention")).not.toBeInTheDocument();
});

it.each([null, "2026-10-02T22:30:00Z"])("keeps an undated or older price retry from hiding a prerequisite failure (%s)", async (retryAt) => {
  show({ backfill: [
    { step: "backfill_funds", status: "failed", done_units: 12, total_units: 44, updated_at: "2026-10-02T23:00:00Z" },
    { step: "backfill_prices", status: "pending", done_units: 0, total_units: null, updated_at: "2026-10-02T22:00:00Z" },
  ], jobs: [{ kind: "backfill_prices", last_status: "queued", last_started_at: retryAt, last_finished_at: null, last_error: null }] });
  expect(await screen.findByText("The historical backfill needs attention before prices can load.")).toBeInTheDocument();
});

it("does not claim active price loading when the job-status query fails", async () => {
  show({});
  server.use(http.get("/api/health", () => HttpResponse.json({ detail: "Unavailable" }, { status: 503 })));
  expect(await screen.findByText("The price job status couldn't be read. Check Data health or try again.")).toBeInTheDocument();
  expect(screen.getByText("Performance is waiting for prices")).toBeInTheDocument();
  expect(screen.queryByText("Performance is loading")).not.toBeInTheDocument();
});

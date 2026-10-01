import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { MemoryRouter } from "react-router";
import { expect, it } from "vitest";
import { health } from "@/mocks/data/health";
import { server } from "@/mocks/node";
import { FreshnessIndicator } from "./FreshnessIndicator";

function show(state: Record<string, unknown>) {
  server.use(http.get("/api/health", () => HttpResponse.json({ ...health(), catch_up: state })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><FreshnessIndicator /></MemoryRouter></QueryClientProvider>);
}

it("shows minutes since the last successful update", async () => {
  show({status: "done", ran: [], behind: [], last_updated_at: new Date(Date.now()-5*60_000).toISOString()});
  expect(await screen.findByText("Updated 5 min ago")).toBeInTheDocument();
});
it("shows catch-up while recovery runs", async () => {
  show({status: "running", ran: [], behind: ["prices_daily"], last_updated_at: null});
  expect(await screen.findByText("Catching up on missed updates…")).toBeInTheDocument();
});
it("warns when updates are behind", async () => {
  show({status: "done", ran: [], behind: ["prices_daily"], last_updated_at: null});
  expect(await screen.findByRole("alert")).toHaveTextContent("Updates behind");
  expect(screen.getByRole("alert")).toHaveAttribute("title", "Behind: prices_daily");
});
it("warns on failed catch-up", async () => {
  show({status: "error", ran: [], behind: [], error: "provider unavailable", last_updated_at: null});
  expect(await screen.findByRole("alert")).toHaveTextContent("Updates behind");
});
it("does not invent freshness before the first update", async () => {
  show({status: "idle", ran: [], behind: [], last_updated_at: null});
  expect(await screen.findByText("Waiting for first update")).toBeInTheDocument();
});
it("shows unavailable status when health cannot be read", async () => {
  server.use(http.get("/api/health", () => new HttpResponse(null,{status:503})));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><FreshnessIndicator /></MemoryRouter></QueryClientProvider>);
  expect(await screen.findByRole("alert")).toHaveTextContent("Update status unavailable");
});

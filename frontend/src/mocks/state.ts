/**
 * Mutable mock state (watchlists and job requests), shared by the browser worker and the
 * node server. Tests reset it after each case so writes never leak between tests.
 *
 * The initial state has zero watchlists on purpose: `useWatch` (F5) creates "My watchlist"
 * on first use, and its test asserts that a POST /api/watchlists happens before the item is
 * added. Pre-seeding a default list here would silently skip that creation step.
 */
import type { Schema } from "@/api/client";
import { FUNDS, ISSUERS, OWNERS } from "./data/world";

type WatchlistOut = Schema<"WatchlistOut">;
type JobRequestOut = Schema<"JobRequestOut">;
type Kind = "insider" | "company" | "fund";

interface State {
  watchlists: WatchlistOut[];
  nextWatchlistId: number;
  jobs: JobRequestOut[];
  nextJobId: number;
}

function freshState(): State {
  return { watchlists: [], nextWatchlistId: 1, jobs: [], nextJobId: 1 };
}

let state: State = freshState();

export function resetMockState(): void {
  state = freshState();
}

function nameFor(kind: Kind, cik: number): string {
  const pool = kind === "insider" ? OWNERS : kind === "fund" ? FUNDS : ISSUERS.map((i) => i.ref);
  return pool.find((p) => p.cik === cik)?.name ?? `${kind} ${cik}`;
}

export function listWatchlists(): WatchlistOut[] {
  return state.watchlists;
}

export function getWatchlist(id: number): WatchlistOut | undefined {
  return state.watchlists.find((w) => w.id === id);
}

export function createWatchlist(name: string): WatchlistOut {
  const watchlist: WatchlistOut = { id: state.nextWatchlistId++, name, items: [] };
  state.watchlists.push(watchlist);
  return watchlist;
}

/** Idempotent: deleting an unknown id is a no-op, matching the contract (204, no 404). */
export function deleteWatchlist(id: number): void {
  state.watchlists = state.watchlists.filter((w) => w.id !== id);
}

export function addWatchlistItem(watchlistId: number, kind: Kind, cik: number): WatchlistOut | undefined {
  const watchlist = getWatchlist(watchlistId);
  if (!watchlist) return undefined;
  if (!watchlist.items.some((item) => item.kind === kind && item.cik === cik)) {
    watchlist.items.push({ kind, cik, name: nameFor(kind, cik), added_at: new Date().toISOString() });
  }
  return watchlist;
}

/** Idempotent: removing an item that isn't there (or from an unknown list) is a no-op. */
export function removeWatchlistItem(watchlistId: number, kind: Kind, cik: number): void {
  const watchlist = getWatchlist(watchlistId);
  if (!watchlist) return;
  watchlist.items = watchlist.items.filter((item) => !(item.kind === kind && item.cik === cik));
}

export function listJobs(limit: number): JobRequestOut[] {
  return state.jobs.slice(0, limit);
}

export function getJob(id: number): JobRequestOut | undefined {
  const job = state.jobs.find((item) => item.id === id);
  // Mock profiles use fixed prices/returns; a scoped refresh finishes at its first poll.
  if (job?.kind === "refresh_insider_performance") {
    job.status = "done";
    job.finished_at = new Date().toISOString();
    job.progress = { ...job.progress, stage: "done", symbols_total: 0, symbols_done: 0, missing: [] };
  }
  return job;
}

export function createJob(kind: string, params: Record<string, unknown> = {}): JobRequestOut {
  const job: JobRequestOut = {
    id: state.nextJobId++,
    kind,
    status: "queued",
    requested_at: new Date().toISOString(),
    finished_at: null,
    error: null,
    progress: kind === "refresh_insider_performance" ? { owner_cik: params.owner_cik } : {},
  };
  state.jobs.unshift(job);
  return job;
}

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, expect, it } from "vitest";
import { AppWithRouter } from "@/App";
import { server } from "@/mocks/node";

let feedRequestUrls: string[] = [];

function onRequestStart({ request }: { request: Request }) {
  if (new URL(request.url).pathname === "/api/feed") feedRequestUrls.push(request.url);
}

beforeEach(() => {
  feedRequestUrls = [];
  server.events.on("request:start", onRequestStart);
});

afterEach(() => {
  server.events.removeListener("request:start", onRequestStart);
});

it("renders feed rows and summary", async () => {
  render(<AppWithRouter initialPath="/" />);
  expect(await screen.findByRole("heading", { name: "Live feed" })).toBeInTheDocument();
  expect(await screen.findByText("Today")).toBeInTheDocument();
  expect((await screen.findAllByText("Doe Jane")).length).toBeGreaterThan(0);
});

it("hide 10b5-1 is on by default", async () => {
  render(<AppWithRouter initialPath="/" />);
  await screen.findByText("Today");
  await waitFor(() => expect(feedRequestUrls.length).toBeGreaterThan(0));
  expect(feedRequestUrls.every((url) => url.includes("include_10b5_1=false"))).toBe(true);
});

it("direction filter updates url and request", async () => {
  const user = userEvent.setup();
  render(<AppWithRouter initialPath="/" />);
  await screen.findByText("Today");
  await user.click(screen.getByText("Buys"));
  await waitFor(() => expect(feedRequestUrls.some((url) => url.includes("direction=buy"))).toBe(true));
});

it("loads next page on scroll end", async () => {
  render(<AppWithRouter initialPath="/" />);
  await screen.findByText("Today");
  const initialRequests = feedRequestUrls.length;
  await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
  await waitFor(() => expect(feedRequestUrls.length).toBeGreaterThan(initialRequests));
  expect(feedRequestUrls.at(-1)).toMatch(/cursor=/);
});

it("empty state", async () => {
  server.use(http.get("/api/feed", () => HttpResponse.json({ items: [], next_cursor: null })));
  render(<AppWithRouter initialPath="/" />);
  expect(await screen.findByText("No filings match these filters")).toBeInTheDocument();
});

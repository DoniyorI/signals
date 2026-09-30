import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, expect, it } from "vitest";
import { api } from "@/api/client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useWatch } from "@/hooks/useWatch";
import { SEED_FEED } from "@/mocks/data/feed";
import { server } from "@/mocks/node";
import WatchlistsPage from "./WatchlistsPage";

let requests: { method: string; url: string }[];
function record({ request }: { request: Request }) {
  requests.push({ method: request.method, url: request.url });
}
beforeEach(() => {
  requests = [];
  server.events.on("request:start", record);
});
afterEach(() => server.events.removeListener("request:start", record));

async function seed(name: string, kind?: "insider" | "company" | "fund", cik?: number) {
  const { data } = await api.POST("/api/watchlists", { body: { name } });
  if (!data) throw new Error("Seed creation failed");
  if (kind && cik) {
    await api.POST("/api/watchlists/{watchlist_id}/items", {
      params: { path: { watchlist_id: data.id } }, body: { kind, cik },
    });
  }
  requests = [];
  return data.id;
}

function WatchStatus() {
  const watch = useWatch("insider", 2000001);
  return <output aria-label="Profile watch status">{watch.isWatched ? "Watching" : "Watch"}</output>;
}

function open(path = "/watchlists", showWatchStatus = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });
  const router = createMemoryRouter([
    { path: "/watchlists", element: <><WatchlistsPage />{showWatchStatus && <WatchStatus />}</> },
  ], { initialEntries: [path] });
  render(<QueryClientProvider client={client}><TooltipProvider><RouterProvider router={router} /></TooltipProvider></QueryClientProvider>);
  return { router, client };
}

it("create posts name and selects the new named list in the URL", async () => {
  open("/watchlists?keep=yes");
  const user = userEvent.setup();
  const input = await screen.findByRole("textbox", { name: "Watchlist name" });
  expect(screen.getByRole("button", { name: "Create watchlist" })).toBeDisabled();
  await user.type(input, "  Research  ");
  await user.click(screen.getByRole("button", { name: "Create watchlist" }));
  expect(await screen.findByRole("heading", { name: "Research" })).toBeInTheDocument();
  const { data } = await api.GET("/api/watchlists", {});
  expect(data).toMatchObject([{ id: 1, name: "Research", items: [] }]);
  expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/watchlists?keep=yes&id=1");
  expect(requests.some((r) => r.method === "POST" && new URL(r.url).pathname === "/api/watchlists")).toBe(true);
  expect(input).toHaveValue("");
});

it("delete asks confirmation and cancel preserves the list before DELETE", async () => {
  const id = await seed("Research", "insider", 2000001);
  await seed("Other");
  const { router } = open(`/watchlists?id=${id}&keep=yes`, true);
  const user = userEvent.setup();
  await screen.findByRole("heading", { name: "Research" });
  expect(await screen.findByLabelText("Profile watch status")).toHaveTextContent("Watching");
  await user.click(screen.getByRole("button", { name: "Delete Research" }));
  let dialog = await screen.findByRole("dialog", { name: "Delete Research?" });
  expect(requests.some((r) => r.method === "DELETE")).toBe(false);
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(requests.some((r) => r.method === "DELETE")).toBe(false);
  await user.click(screen.getByRole("button", { name: "Delete Research" }));
  dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Delete watchlist" }));
  await screen.findByRole("heading", { name: "Other" });
  expect(screen.queryByRole("link", { name: "Research" })).not.toBeInTheDocument();
  expect(router.state.location.search).toBe("?id=2&keep=yes");
  expect(screen.getByLabelText("Profile watch status")).toHaveTextContent(/^Watch$/);
  expect(requests.filter((r) => r.method === "DELETE").map((r) => new URL(r.url).pathname)).toEqual(["/api/watchlists/1"]);
});

it("activity renders feed rows only for the URL-selected list and switching updates id", async () => {
  await seed("Jane", "insider", 2000001);
  await seed("Funds", "fund", 3000001);
  const { router } = open("/watchlists?id=2");
  const activity = await screen.findByRole("region", { name: "Activity" });
  expect((await within(activity).findAllByRole("link", { name: "Example Capital Management" }))[0]).toHaveAttribute("href", "/fund/3000001");
  expect(within(activity).queryByRole("link", { name: "Doe Jane" })).not.toBeInTheDocument();
  const sec = within(activity).getAllByRole("link", { name: "SEC" })[0];
  expect(sec).toHaveAttribute("target", "_blank");
  expect(sec).toHaveAttribute("rel", "noreferrer");
  await userEvent.setup().click(screen.getByRole("link", { name: "Jane" }));
  expect(router.state.location.search).toBe("?id=1");
  expect(await within(activity).findAllByRole("link", { name: "Doe Jane" })).not.toHaveLength(0);
  expect(within(activity).queryByRole("link", { name: "Example Capital Management" })).not.toBeInTheDocument();
});

it("items link by kind and CIK; removing an item refreshes activity and profile watch state", async () => {
  const id = await seed("Research", "insider", 2000001);
  for (const item of [{ kind: "company" as const, cik: 1000001 }, { kind: "fund" as const, cik: 3000001 }]) {
    await api.POST("/api/watchlists/{watchlist_id}/items", { params: { path: { watchlist_id: id } }, body: item });
  }
  open(`/watchlists?id=${id}`, true);
  const items = await screen.findByRole("region", { name: "Items" });
  expect(within(items).getByRole("link", { name: "Doe Jane" })).toHaveAttribute("href", "/insider/2000001");
  expect(within(items).getByRole("link", { name: "Acme Corp" })).toHaveAttribute("href", "/company/1000001");
  expect(within(items).getByRole("link", { name: "Example Capital Management" })).toHaveAttribute("href", "/fund/3000001");
  const user = userEvent.setup();
  await user.click(within(items).getByRole("button", { name: "Remove Doe Jane" }));
  await waitFor(() => expect(within(items).queryByRole("link", { name: "Doe Jane" })).not.toBeInTheDocument());
  expect(screen.getByLabelText("Profile watch status")).toHaveTextContent(/^Watch$/);
  await user.click(within(items).getByRole("button", { name: "Remove Acme Corp" }));
  await waitFor(() => expect(within(items).getByRole("button", { name: "Remove Example Capital Management" })).toBeEnabled());
  await user.click(within(items).getByRole("button", { name: "Remove Example Capital Management" }));
  expect(await screen.findByText("No items in this watchlist")).toBeInTheDocument();
  expect(await screen.findByText("No activity for this watchlist")).toBeInTheDocument();
  expect(requests.some((r) => r.method === "DELETE" && new URL(r.url).pathname === "/api/watchlists/1/items/insider/2000001")).toBe(true);
});

it("activity appends the next page using the opaque cursor", async () => {
  await seed("Research", "company", 1000001);
  server.use(http.get("/api/watchlists/1/activity", ({ request }) => {
    const cursor = new URL(request.url).searchParams.get("cursor");
    return HttpResponse.json({ items: [SEED_FEED[cursor ? 1 : 0]], next_cursor: cursor ? null : "opaque-next" });
  }));
  open("/watchlists?id=1");
  const activity = await screen.findByRole("region", { name: "Activity" });
  await within(activity).findByRole("link", { name: "Doe Jane" });
  await userEvent.setup().click(within(activity).getByRole("button", { name: "Load more" }));
  expect(await within(activity).findByRole("link", { name: "Roe Richard" })).toBeInTheDocument();
  expect(within(activity).getByRole("link", { name: "Doe Jane" })).toBeInTheDocument();
  expect(within(activity).queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  const activityRequests = requests.filter((r) => r.url.includes("/activity"));
  expect(new URL(activityRequests[1].url).searchParams.get("cursor")).toBe("opaque-next");
});

it("pagination shows a disabled loading control and retains existing rows while fetching", async () => {
  await seed("Research", "company", 1000001);
  let finishPage: (() => void) | undefined;
  server.use(http.get("/api/watchlists/1/activity", async ({ request }) => {
    if (new URL(request.url).searchParams.has("cursor")) {
      await new Promise<void>((resolve) => { finishPage = resolve; });
      return HttpResponse.json({ items: [SEED_FEED[1]], next_cursor: null });
    }
    return HttpResponse.json({ items: [SEED_FEED[0]], next_cursor: "next-page" });
  }));
  open("/watchlists?id=1");
  const activity = await screen.findByRole("region", { name: "Activity" });
  await within(activity).findByRole("link", { name: "Doe Jane" });
  await userEvent.setup().click(within(activity).getByRole("button", { name: "Load more" }));
  try {
    expect(within(activity).getByRole("button", { name: "Loading…" })).toBeDisabled();
    expect(within(activity).getByRole("link", { name: "Doe Jane" })).toBeInTheDocument();
  } finally {
    await waitFor(() => expect(finishPage).toBeTypeOf("function"));
    finishPage?.();
  }
  expect(await within(activity).findByRole("link", { name: "Roe Richard" })).toBeInTheDocument();
});

it("empty lists and unknown URL ids show actionable empty states", async () => {
  const { router } = open("/watchlists?id=999");
  expect(await screen.findByText("No watchlists yet")).toBeInTheDocument();
  expect(requests.some((r) => r.url.includes("/activity"))).toBe(false);
  const user = userEvent.setup();
  await user.type(screen.getByRole("textbox", { name: "Watchlist name" }), "Research");
  await user.click(screen.getByRole("button", { name: "Create watchlist" }));
  await screen.findByRole("heading", { name: "Research" });
  await router.navigate("/watchlists?id=999");
  expect(await screen.findByText("Watchlist not found")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Research" })).toBeInTheDocument();
});

it("list load failure can be retried", async () => {
  await seed("Research");
  server.use(http.get("/api/watchlists", () => new HttpResponse(null, { status: 500 })));
  open();
  await screen.findByText("Watchlists didn't load", {}, { timeout: 3000 });
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { name: "Research" })).toBeInTheDocument();
});

it("failed create preserves the name and shows the error", async () => {
  server.use(http.post("/api/watchlists", () => new HttpResponse(null, { status: 500 })));
  open();
  const user = userEvent.setup();
  await user.type(await screen.findByRole("textbox", { name: "Watchlist name" }), "Research");
  await user.click(screen.getByRole("button", { name: "Create watchlist" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not create the watchlist");
  expect(screen.getByRole("textbox", { name: "Watchlist name" })).toHaveValue("Research");
});

it("failed deletion keeps its confirmation and does not remove the list", async () => {
  await seed("Research");
  server.use(http.delete("/api/watchlists/1", () => new HttpResponse(null, { status: 500 })));
  open("/watchlists?id=1");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Delete Research" }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Delete watchlist" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent("Could not delete the watchlist");
  expect(screen.getByRole("heading", { name: "Research", hidden: true })).toBeInTheDocument();
});

it("failed item removal leaves the item visible", async () => {
  await seed("Research", "insider", 2000001);
  server.use(http.delete("/api/watchlists/1/items/insider/2000001", () => new HttpResponse(null, { status: 500 })));
  open("/watchlists?id=1");
  await userEvent.setup().click(await screen.findByRole("button", { name: "Remove Doe Jane" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not remove the item");
  expect(within(screen.getByRole("region", { name: "Items" })).getByRole("link", { name: "Doe Jane" })).toBeInTheDocument();
});

it("activity errors stay visible with a retry while items remain usable", async () => {
  await seed("Research", "insider", 2000001);
  server.use(http.get("/api/watchlists/1/activity", () => new HttpResponse(null, { status: 500 })));
  open("/watchlists?id=1");
  expect(await screen.findByText("Activity didn't load", {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Remove Doe Jane" })).toBeInTheDocument();
  server.resetHandlers();
  await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
  expect(await within(screen.getByRole("region", { name: "Activity" })).findAllByRole("link", { name: "Doe Jane" })).not.toHaveLength(0);
});

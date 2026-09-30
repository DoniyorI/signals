import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, type Schema } from "@/api/client";
import { DataTable } from "@/components/data/DataTable";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorState } from "@/components/state/ErrorState";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { required, retryUnlessNotFound } from "@/lib/httpError";
import { feedColumns } from "./feed/feedColumns";

type Watchlist = Schema<"WatchlistOut">;
type Item = Schema<"WatchlistItemOut">;

export default function WatchlistsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Watchlist | null>(null);
  const id = searchParams.get("id");
  const watchlists = useQuery({
    queryKey: ["watchlists"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/watchlists", {});
      return required(data, response);
    },
    retry: retryUnlessNotFound,
  });
  const lists = watchlists.data ?? [];
  const selected = id === null ? lists[0] : lists.find((list) => String(list.id) === id);

  function select(listId: number | undefined) {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      if (listId === undefined) next.delete("id");
      else next.set("id", String(listId));
      return next;
    });
  }

  // First visits choose a list and save that selection, so the resulting view can be shared.
  const firstId = id === null ? lists[0]?.id : undefined;
  useEffect(() => {
    if (firstId === undefined) return;
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      if (!next.has("id")) next.set("id", String(firstId));
      return next;
    }, { replace: true });
  }, [firstId, setSearchParams]);

  const activity = useInfiniteQuery({
    queryKey: ["watchlist-activity", selected?.id],
    enabled: selected !== undefined,
    queryFn: async ({ pageParam }: { pageParam: string | undefined }) => {
      if (!selected) throw new Error("No watchlist selected");
      const { data, response } = await api.GET("/api/watchlists/{watchlist_id}/activity", {
        params: { path: { watchlist_id: selected.id }, query: { cursor: pageParam, limit: 50 } },
      });
      return required(data, response);
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    retry: retryUnlessNotFound,
  });

  const create = useMutation({
    mutationFn: async (listName: string) => {
      const { data, response } = await api.POST("/api/watchlists", { body: { name: listName } });
      return required(data, response);
    },
    onSuccess: async (created) => {
      queryClient.setQueryData<Watchlist[]>(["watchlists"], (previous) => [...(previous ?? []), created]);
      setName("");
      select(created.id);
      await queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });

  const removeList = useMutation({
    mutationFn: async (listId: number) => {
      const { response } = await api.DELETE("/api/watchlists/{watchlist_id}", {
        params: { path: { watchlist_id: listId } },
      });
      if (!response.ok) throw new Error("Could not delete the watchlist");
    },
    onSuccess: async (_, removedId) => {
      const remaining = (queryClient.getQueryData<Watchlist[]>(["watchlists"]) ?? [])
        .filter((list) => list.id !== removedId);
      queryClient.setQueryData(["watchlists"], remaining);
      if (selected?.id === removedId) select(remaining[0]?.id);
      setDeleteTarget(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["watchlists"] }),
        queryClient.invalidateQueries({ queryKey: ["watchlist-activity"] }),
      ]);
    },
  });

  const removeItem = useMutation({
    mutationFn: async ({ listId, item }: { listId: number; item: Item }) => {
      const { response } = await api.DELETE("/api/watchlists/{watchlist_id}/items/{kind}/{cik}", {
        params: { path: { watchlist_id: listId, kind: item.kind, cik: item.cik } },
      });
      if (!response.ok) throw new Error("Could not remove the item");
    },
    onSuccess: async (_, { listId, item }) => {
      queryClient.setQueryData<Watchlist[]>(["watchlists"], (previous) => previous?.map((list) =>
        list.id !== listId ? list : {
          ...list,
          items: list.items.filter((entry) => entry.kind !== item.kind || entry.cik !== item.cik),
        },
      ));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["watchlists"] }),
        queryClient.invalidateQueries({ queryKey: ["watchlist-activity", listId] }),
      ]);
    },
  });

  const rows = activity.data?.pages.flatMap((page) => page.items) ?? [];

  function loadMore() {
    if (!activity.isFetching) void activity.fetchNextPage();
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <h1 className="text-xl font-semibold">Watchlists</h1>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim() && !create.isPending) create.mutate(name.trim());
        }}
      >
        <div className="w-full sm:w-64">
          <label htmlFor="watchlist-name" className="mb-1 block text-xs text-muted-foreground">Watchlist name</label>
          <Input
            id="watchlist-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={create.isPending}
          />
        </div>
        <Button type="submit" disabled={!name.trim() || create.isPending}>{create.isPending ? "Creating…" : "Create watchlist"}</Button>
      </form>
      {create.isError && <p role="alert" className="text-sm text-neg">Could not create the watchlist. Try again.</p>}
      {watchlists.isPending ? <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p> : watchlists.isError ? (
        <ErrorState title="Watchlists didn't load" action={<Button variant="outline" onClick={() => watchlists.refetch()}>Try again</Button>} />
      ) : lists.length === 0 ? (
        <EmptyState title="No watchlists yet" description="Create a named list, then use Watch on a company, insider, or fund profile to add items." />
      ) : (
        <div className="grid min-w-0 gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
          <nav aria-label="Your watchlists" className="self-start rounded-md border border-border bg-card p-2">
            <ul className="space-y-1">
              {lists.map((list) => {
                const params = new URLSearchParams(searchParams);
                params.set("id", String(list.id));
                return (
                  <li key={list.id} className="flex min-w-0 items-center gap-1">
                    <Link
                      to={`/watchlists?${params}`}
                      aria-current={selected?.id === list.id ? "page" : undefined}
                      className="min-w-0 flex-1 rounded px-2 py-2 text-sm break-words hover:bg-muted aria-[current=page]:bg-muted aria-[current=page]:font-medium"
                    >
                      {list.name}
                    </Link>
                    <Button
                      size="xs"
                      variant="ghost"
                      aria-label={`Delete ${list.name}`}
                      onClick={() => { removeList.reset(); setDeleteTarget(list); }}
                    >
                      Delete
                    </Button>
                  </li>
                );
              })}
            </ul>
          </nav>
          {selected ? (
            <div className="flex min-w-0 flex-col gap-4">
              <h2 className="text-lg font-semibold break-words">{selected.name}</h2>
              <section aria-label="Items" className="rounded-md border border-border bg-card p-4">
                <h3 className="mb-2 text-sm font-semibold">Items</h3>
                {removeItem.isError && <p role="alert" className="mb-2 text-sm text-neg">Could not remove the item. Try again.</p>}
                {selected.items.length === 0 ? (
                  <EmptyState
                    title="No items in this watchlist"
                    description="Use Watch on a profile to add it to your first watchlist."
                  />
                ) : (
                  <ul className="divide-y divide-border">
                    {selected.items.map((item) => (
                      <li key={`${item.kind}:${item.cik}`} className="flex min-w-0 items-center justify-between gap-2 py-2 text-sm">
                        <div className="min-w-0">
                          <Link to={`/${item.kind}/${item.cik}`} className="text-link break-words hover:underline">
                            {item.name}
                          </Link>
                          <span className="ml-2 text-xs text-muted-foreground">{item.kind} · CIK {item.cik}</span>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Remove ${item.name}`}
                          disabled={removeItem.isPending}
                          onClick={() => removeItem.mutate({ listId: selected.id, item })}
                        >
                          Remove
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section aria-label="Activity" className="min-w-0">
                <h3 className="mb-2 text-sm font-semibold">Activity</h3>
                {activity.isPending ? <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p> : (
                  <>
                    {activity.isError && (
                      <ErrorState
                        title="Activity didn't load"
                        action={
                          <Button
                            variant="outline"
                            onClick={() => activity.isFetchNextPageError ? activity.fetchNextPage() : activity.refetch()}
                          >
                            Try again
                          </Button>
                        }
                      />
                    )}
                    {activity.data && (
                      <DataTable
                        columns={feedColumns}
                        data={rows}
                        getRowId={(row) => row.accession_no}
                        onEndReached={activity.hasNextPage ? loadMore : undefined}
                        isFetchingMore={activity.isFetchingNextPage}
                        rowClassName={(row) => row.direction === "buy" ? "border-l-[3px] border-l-pos"
                          : row.direction === "sell" ? "border-l-[3px] border-l-neg" : undefined}
                        empty={<EmptyState title="No activity for this watchlist" />}
                      />
                    )}
                  </>
                )}
              </section>
            </div>
          ) : <EmptyState title="Watchlist not found" description="Choose one of your lists to view its items and activity." />}
        </div>
      )}
      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(isOpen) => { if (!isOpen && !removeList.isPending) setDeleteTarget(null); }}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete {deleteTarget?.name}?</DialogTitle>
            <DialogDescription>This deletes the watchlist and removes all its items.</DialogDescription>
          </DialogHeader>
          {removeList.isError && <p role="alert" className="text-sm text-neg">Could not delete the watchlist. Try again.</p>}
          <DialogFooter>
            <Button variant="outline" disabled={removeList.isPending} onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              disabled={removeList.isPending}
              onClick={() => { if (deleteTarget) removeList.mutate(deleteTarget.id); }}
            >
              {removeList.isPending ? "Deleting…" : "Delete watchlist"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Schema } from "@/api/client";

type Kind = Schema<"WatchlistItemCreate">["kind"];
type WatchlistOut = Schema<"WatchlistOut">;

/**
 * Whether `kind`/`cik` is on any watchlist, and a `watch()` action that adds it — creating
 * "My watchlist" first if the user has none yet (plan 07, F5). Mock state starts with zero
 * watchlists on purpose (see `src/mocks/state.ts`), so the very first watch anywhere creates
 * one; `watch()` always re-reads the watchlist list itself rather than trusting this hook's own
 * query to have settled first, so it's correct even if called before that query resolves.
 */
export function useWatch(kind: Kind, cik: number) {
  const queryClient = useQueryClient();

  const watchlists = useQuery({
    queryKey: ["watchlists"],
    queryFn: async () => {
      const { data } = await api.GET("/api/watchlists", {});
      return data ?? [];
    },
  });

  const mutation = useMutation({
    mutationFn: async () => {
      const { data: existing } = await api.GET("/api/watchlists", {});
      let target = existing?.[0];
      if (!target) {
        const created = await api.POST("/api/watchlists", { body: { name: "My watchlist" } });
        if (!created.data) throw new Error("Could not create a watchlist.");
        target = created.data;
      }
      const added = await api.POST("/api/watchlists/{watchlist_id}/items", {
        params: { path: { watchlist_id: target.id } },
        body: { kind, cik },
      });
      if (!added.data) throw new Error("Could not add to the watchlist.");
      return added.data;
    },
    onSuccess: (watchlist: WatchlistOut) => {
      queryClient.setQueryData(["watchlists"], (prev: WatchlistOut[] | undefined) => [
        ...(prev ?? []).filter((w) => w.id !== watchlist.id),
        watchlist,
      ]);
      void queryClient.invalidateQueries({ queryKey: ["watchlists"] });
    },
  });

  const isWatched = (watchlists.data ?? []).some((w) => w.items.some((item) => item.kind === kind && item.cik === cik));

  return {
    isWatched,
    isPending: mutation.isPending,
    watch: () => mutation.mutate(),
  };
}

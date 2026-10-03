import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api, type Schema } from "@/api/client";
import { required } from "@/lib/httpError";

const active = new Set(["requested", "queued", "pending", "running"]);
type RefreshRequest = { job: Schema<"JobRequestOut">; applied: "pending" | "refreshing" | "done" };

function jobResponse(data: Schema<"JobRequestOut"> | undefined, error: unknown, response: Response) {
  if (!data && error && typeof error === "object" && "detail" in error && typeof error.detail === "string") {
    throw new Error(error.detail);
  }
  return required(data, response);
}

/** Keep the one-shot request in the owner's query cache, shared across basis changes.
 * Only the worker loads prices/calculates returns; the profile polls its own job. */
export function useInsiderPerformanceRefresh(cik: number, enabled: boolean) {
  const client = useQueryClient();
  const requestKey = ["insider-performance-refresh", cik] as const;
  const request = useQuery({
    queryKey: requestKey,
    queryFn: async (): Promise<RefreshRequest> => {
      const { data, error, response } = await api.POST("/api/jobs", {
        body: { kind: "refresh_insider_performance", params: { owner_cik: cik } },
      });
      return { job: jobResponse(data, error, response), applied: "pending" };
    },
    enabled,
    staleTime: Infinity,
    retry: false,
    retryOnMount: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const id = request.data?.job.id;
  const detail = useQuery({
    queryKey: ["job", id],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id! } } });
      return jobResponse(data, error, response);
    },
    enabled: id !== undefined,
    staleTime: 0,
    refetchInterval: (query) => active.has(query.state.data?.status ?? request.data?.job.status ?? "") ? 1_000 : false,
    refetchOnWindowFocus: false,
  });
  const job = detail.data ?? request.data?.job;

  useEffect(() => {
    const key = ["insider-performance-refresh", cik] as const;
    const cached = client.getQueryData<RefreshRequest>(key);
    if (job?.status !== "done" || !cached || cached.applied !== "pending") return;
    // Mark before invalidating so remounts and concurrent observers cannot repeat it.
    client.setQueryData<RefreshRequest>(key, { ...cached, applied: "refreshing" });
    void Promise.all([
      client.invalidateQueries({ queryKey: ["insider-header", cik] }),
      client.invalidateQueries({ queryKey: ["insider-performance", cik] }),
      client.invalidateQueries({ queryKey: ["insider-decisions", cik] }),
    ]).then(() => {
      client.setQueryData<RefreshRequest>(key, (current) => current ? { ...current, applied: "done" } : current);
    });
  }, [client, cik, job?.status]);

  return {
    job,
    isStarting: enabled && request.isPending,
    isRefreshing: job?.status === "done" && request.data?.applied !== "done",
    isDone: job?.status === "done" && request.data?.applied === "done",
    requestError: request.isError ? request.error : null,
    statusError: detail.isError ? detail.error : null,
  };
}

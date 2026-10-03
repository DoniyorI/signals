import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { required } from "@/lib/httpError";

/** A shared, read-only global snapshot. Consumers combine it with local evidence; a low
 * pct alone cannot diagnose an entity or establish that a price job is running. */
export function useCoverage(enabled = true) {
  return useQuery({
    queryKey: ["health", "completeness"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/health/completeness");
      return required(data, response);
    },
    enabled,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "@/api/client";
import { required } from "@/lib/httpError";

export function FreshnessIndicator() {
  const query = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/health");
      return required(data, response);
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
  const state = query.data?.catch_up;
  const behind = state?.behind ?? [];
  let label = "Checking for updates…";
  let warning = false;
  let title: string | undefined;
  if (query.isError) {
    label = "Update status unavailable";
    warning = true;
  } else if (state?.status === "running") {
    label = "Catching up on missed updates…";
  } else if (state && (behind.length > 0 || state.status === "error")) {
    label = "Updates behind";
    warning = true;
    title = behind.length ? `Behind: ${behind.join(", ")}` : state.error ?? undefined;
  } else if (state?.last_updated_at) {
    const minutes = Math.max(0, Math.floor((query.dataUpdatedAt - Date.parse(state.last_updated_at)) / 60_000));
    label = `Updated ${minutes} min ago`;
  } else if (state) {
    label = "Waiting for first update";
  }
  return <Link to="/health" role={warning ? "alert" : "status"} title={title}
    className={`text-xs ${warning ? "text-warn" : "text-muted-foreground"}`}>
    {label}
  </Link>;
}

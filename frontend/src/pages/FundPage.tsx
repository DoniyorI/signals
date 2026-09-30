import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { api } from "@/api/client";
import { ErrorState } from "@/components/state/ErrorState";
import { isNotFound, required, retryUnlessNotFound } from "@/lib/httpError";
import { FundHeader } from "./fund/FundHeader";
import { FundHoldings } from "./fund/FundHoldings";
import { FundPerformance } from "./fund/FundPerformance";

export default function FundPage() {
  const { cik: cikParam } = useParams();
  const cik = Number(cikParam);

  const headerQuery = useQuery({
    queryKey: ["fund-header", cik],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/funds/{cik}", { params: { path: { cik } } });
      return required(data, response);
    },
    retry: retryUnlessNotFound,
  });

  if (headerQuery.status === "pending") {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (headerQuery.status === "error") {
    return isNotFound(headerQuery.error) ? (
      <ErrorState title="Fund not found" />
    ) : (
      <ErrorState
        title="Something went wrong"
        action={
          <button type="button" onClick={() => headerQuery.refetch()} className="text-sm text-link hover:underline">
            Try again
          </button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <FundHeader fund={headerQuery.data} />
      <FundPerformance cik={cik} />
      <FundHoldings cik={cik} />
    </div>
  );
}

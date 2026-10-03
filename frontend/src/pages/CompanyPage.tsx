import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { api } from "@/api/client";
import { PriceChart } from "@/components/charts/PriceChart";
import { ErrorState } from "@/components/state/ErrorState";
import { CoverageEmptyState } from "@/components/state/CoverageEmptyState";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useUrlState } from "@/hooks/useUrlState";
import { isNotFound, required, retryUnlessNotFound } from "@/lib/httpError";
import { CompanyForm144Tab } from "./company/CompanyForm144Tab";
import { CompanyHeader } from "./company/CompanyHeader";
import { InsidersTab } from "./company/InsidersTab";
import { InstitutionsTab } from "./company/InstitutionsTab";
import { StakesTab } from "./company/StakesTab";

type Tab = "insiders" | "institutions" | "stakes" | "form144";

function parseTab(raw: string | null): Tab {
  return raw === "institutions" || raw === "stakes" || raw === "form144" ? raw : "insiders";
}

/** `ref` is a CIK (all digits) or a ticker — current, else the latest former holder (spec 11,
 * company page: `/company/:ref`). */
export default function CompanyPage() {
  const { ref = "" } = useParams();
  const [tab, setTab] = useUrlState<Tab>("tab", "insiders", parseTab, (v) => v);

  const companyQuery = useQuery({
    queryKey: ["company", ref],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/companies/{ref}", { params: { path: { ref } } });
      return required(data, response);
    },
    retry: retryUnlessNotFound,
  });

  if (companyQuery.status === "pending") {
    return <p className="py-10 text-center text-sm text-muted-foreground">Loading…</p>;
  }
  if (companyQuery.status === "error") {
    return isNotFound(companyQuery.error) ? (
      <ErrorState title="Company not found" />
    ) : (
      <ErrorState
        title="Something went wrong"
        action={
          <button type="button" onClick={() => companyQuery.refetch()} className="text-sm text-link hover:underline">
            Try again
          </button>
        }
      />
    );
  }

  const company = companyQuery.data;
  const cik = company.cik;

  return (
    <div className="flex flex-col gap-6">
      <CompanyHeader company={company} />
      <PricesSection cik={cik} />
      <Tabs value={tab} onValueChange={(v) => setTab(parseTab(v))}>
        <TabsList>
          <TabsTrigger value="insiders">Insiders</TabsTrigger>
          <TabsTrigger value="institutions">Institutions</TabsTrigger>
          <TabsTrigger value="stakes">Stakes</TabsTrigger>
          <TabsTrigger value="form144">Form 144</TabsTrigger>
        </TabsList>
        <TabsContent value={tab}>
          {tab === "insiders" && <InsidersTab cik={cik} />}
          {tab === "institutions" && <InstitutionsTab cik={cik} />}
          {tab === "stakes" && <StakesTab cik={cik} />}
          {tab === "form144" && <CompanyForm144Tab cik={cik} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** The last 3 years of price bars, with buy/sell/144/stake/cluster markers (spec 11). Omitting
 * `start`/`end` already gets the last 3 years from the mock/API default. */
function PricesSection({ cik }: { cik: number }) {
  const query = useQuery({
    queryKey: ["company-prices", cik],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/companies/{cik}/prices", { params: { path: { cik }, query: {} } });
      return required(data, response);
    },
  });

  if (query.isPending) return <p className="py-10 text-center text-sm text-muted-foreground">Loading prices…</p>;
  if (query.isError) return <ErrorState title="Prices didn't load"
    action={<button type="button" className="text-sm text-link hover:underline" onClick={() => { void query.refetch(); }}>Try again</button>} />;
  if (query.data.bars.length === 0) return <CoverageEmptyState notCovered={query.data.symbol === null} allowLoading noPricesWhenIdle />;
  return <PriceChart bars={query.data.bars} markers={query.data.markers} />;
}

import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { required } from "@/lib/httpError";

const queued = new Set(["pending", "requested", "queued"]);
const failed = new Set(["failed", "error"]);
const priceKinds = new Set(["backfill_prices", "prices_daily"]);
const stepLabels: Record<string, string> = {
  backfill_reference: "company reference updates",
  backfill_insiders: "insider filings",
  backfill_funds: "fund filings",
  backfill_stakes: "stake filings",
  backfill_form144: "Form 144 notices",
};

/** Completeness.loading includes queued work. Reuse the header's health snapshot to show
 * whether prices are actually running, waiting for another step, or need recovery. */
export function usePriceLoadStatus(enabled: boolean) {
  const query = useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, response } = await api.GET("/api/health");
      return required(data, response);
    },
    enabled,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  let state: "running" | "queued" | "failed" | "unknown" = "unknown";
  let explanation: string | undefined;
  if (query.data && !query.isError) {
    const { backfill, jobs } = query.data;
    const priceStep = backfill.find((step) => step.step === "backfill_prices");
    const priceJobs = jobs.filter((job) => priceKinds.has(job.kind));
    const activeStep = backfill.find((step) => step.step !== "backfill_prices" && !step.step.includes(".") && step.status === "running");
    const failedPrerequisite = backfill.some((step) => step.step !== "backfill_prices" && step.step.startsWith("backfill_") &&
      !step.step.includes(".") && failed.has(step.status)) || jobs.some((job) => job.kind === "backfill_all" && failed.has(job.last_status ?? ""));
    const latestPriceJob = priceJobs.sort((left, right) =>
      (right.last_finished_at ?? right.last_started_at ?? "").localeCompare(left.last_finished_at ?? left.last_started_at ?? ""))[0];
    if (priceStep?.status === "running" || priceJobs.some((job) => job.last_status === "running")) state = "running";
    else if (priceStep && failed.has(priceStep.status)) {
      state = "failed";
      explanation = "Price loading failed. Check Data health for the error and retry status.";
    } else if (priceStep && queued.has(priceStep.status)) {
      if (failedPrerequisite) {
        state = "failed";
        explanation = "The historical backfill needs attention before prices can load.";
      } else {
        state = "queued";
        explanation = activeStep ? `Price loading is queued while ${stepLabels[activeStep.step] ?? "other backfill steps"} finish.` :
          "Price loading is queued and has not started yet.";
      }
    } else if (latestPriceJob && queued.has(latestPriceJob.last_status ?? "")) {
      state = "queued";
      explanation = "Price loading is queued and has not started yet.";
    } else if (latestPriceJob && failed.has(latestPriceJob.last_status ?? "") &&
      (priceStep?.status !== "done" || (latestPriceJob.last_finished_at ?? latestPriceJob.last_started_at ?? "") > (priceStep.updated_at ?? ""))) {
      state = "failed";
      explanation = "Price loading failed. Check Data health for the error and retry status.";
    }
  }
  return { state, explanation, isError: query.isError };
}

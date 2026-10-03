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

function timestamp(value: string | null | undefined): number | null {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

function jobTimestamp(job: { last_finished_at: string | null; last_started_at: string | null }): number | null {
  return timestamp(job.last_finished_at ?? job.last_started_at);
}

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
    const failedPrerequisiteSteps = backfill.filter((step) => step.step !== "backfill_prices" && step.step.startsWith("backfill_") &&
      !step.step.includes(".") && failed.has(step.status));
    const failedParentJobs = jobs.filter((job) => job.kind === "backfill_all" && failed.has(job.last_status ?? ""));
    const failedPrerequisite = failedPrerequisiteSteps.length > 0 || failedParentJobs.length > 0;
    const latestPriceJob = priceJobs.sort((left, right) =>
      (jobTimestamp(right) ?? 0) - (jobTimestamp(left) ?? 0))[0];
    const latestPriceJobTime = latestPriceJob ? jobTimestamp(latestPriceJob) : null;
    const historicalTimes = [
      ...(priceStep ? [timestamp(priceStep.updated_at)] : []),
      ...failedPrerequisiteSteps.map((step) => timestamp(step.updated_at)),
      ...failedParentJobs.map(jobTimestamp),
    ];
    // A standalone retry can recover prices without rerunning old prerequisites. Only
    // supersede the historical snapshot when all timestamps establish that it is newer.
    const newerQueuedPriceRetry = latestPriceJob && queued.has(latestPriceJob.last_status ?? "") &&
      latestPriceJobTime !== null && historicalTimes.every((time) => time !== null && latestPriceJobTime > time);
    if (priceStep?.status === "running" || priceJobs.some((job) => job.last_status === "running")) state = "running";
    else if (newerQueuedPriceRetry) {
      state = "queued";
      explanation = "Price loading is queued and has not started yet.";
    } else if (priceStep && failed.has(priceStep.status)) {
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
      (priceStep?.status !== "done" || (latestPriceJobTime ?? 0) > (timestamp(priceStep.updated_at) ?? 0))) {
      state = "failed";
      explanation = "Price loading failed. Check Data health for the error and retry status.";
    }
  }
  return { state, explanation, isError: query.isError };
}

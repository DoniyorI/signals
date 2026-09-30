/**
 * A typed error for a failed API response, so pages can distinguish "not found" (an expected,
 * renderable state — ground rule 5, no silent failures) from a genuine network/server error.
 * openapi-fetch decides `data` vs `error` by `response.ok`, not by which status codes a path
 * happens to document (see `src/api/schema.d.ts`), so an undocumented 404 — e.g.
 * `/api/companies/{ref}` for an unknown ref, or `/api/funds/{cik}/performance` for an untracked
 * fund — still lands here with the real status instead of throwing away the information.
 */
export class HttpError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Request failed with status ${status}`);
    this.name = "HttpError";
    this.status = status;
  }
}

/** Unwraps an openapi-fetch result, throwing `HttpError` when the response wasn't ok. */
export function required<T>(data: T | undefined, response: Response): T {
  if (data === undefined) throw new HttpError(response.status);
  return data;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof HttpError && error.status === 404;
}

/**
 * A TanStack Query `retry` option that never retries a 404 (the app's own query-client default
 * otherwise retries once): a 404 here means "this profile doesn't exist" or "performance isn't
 * available for this fund" — a fact that won't change on retry — so retrying only delays
 * showing the right message. Any other error still gets the app's usual one retry.
 */
export function retryUnlessNotFound(failureCount: number, error: unknown): boolean {
  return !isNotFound(error) && failureCount < 1;
}

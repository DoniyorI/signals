import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";
import { server } from "@/mocks/node";
import { resetMockState } from "@/mocks/state";

// Listening here (a setup-file side effect), rather than in `beforeAll`, patches
// `globalThis.fetch` before any test file imports `@/api/client`. openapi-fetch's
// `createClient` captures `globalThis.fetch` as a default argument at import time, so if MSW
// patched it later (inside `beforeAll`, which runs after the test file's module graph is
// already loaded), the typed `api` client would bypass MSW and hit the real network.
server.listen({ onUnhandledRequest: "error" });
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetMockState();
});
afterAll(() => server.close());

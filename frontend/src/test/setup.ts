import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";
import { server } from "@/mocks/node";
import { resetMockState } from "@/mocks/state";

// jsdom implements neither observer: charts (lightweight-charts' resize handling, Recharts'
// ResponsiveContainer) and some Radix primitives expect at least a no-op ResizeObserver.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom never computes layout, so every element reports 0 for offsetWidth/offsetHeight.
// @tanstack/react-virtual sizes its viewport from exactly those two properties, and with a
// 0-height viewport it virtualizes zero rows — DataTable would render an empty <tbody> in
// every test. A fixed non-zero default (overridable per element with `Object.defineProperty`,
// as the "calls onEndReached" test does for scroll metrics) fixes that project-wide.
Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 1024 });
Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 768 });

// jsdom implements none of these: Radix's `Select` (and other pointer-capture-aware primitives)
// call them from their pointer-down handling, which throws "not a function" the first time a
// test opens a Select in jsdom otherwise (ledger Ruling F6.1).
for (const method of ["hasPointerCapture", "setPointerCapture", "releasePointerCapture"] as const) {
  if (typeof Element.prototype[method] === "undefined") {
    Object.defineProperty(Element.prototype, method, { configurable: true, value: () => false });
  }
}
if (typeof Element.prototype.scrollIntoView === "undefined") {
  Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: () => {} });
}

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

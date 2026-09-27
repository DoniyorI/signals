import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

// Absolute base so requests also work in tests (jsdom) and behind the Vite /api proxy.
const baseUrl = typeof window !== "undefined" ? window.location.origin : "http://localhost";

export const api = createClient<paths>({ baseUrl });

export type Schema<K extends keyof components["schemas"]> = components["schemas"][K];

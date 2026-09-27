import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { isMock } from "./lib/env";
import "./index.css";

async function enableMocking() {
  if (!isMock) return;
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

enableMocking().then(() => {
  const root = document.getElementById("root");
  if (!root) throw new Error("#root element missing");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});

import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { EmptyState } from "./EmptyState";

it("renders loading reason with percent", () => {
  render(<EmptyState reason="loading" percent={37} />);
  expect(screen.getByText("Performance appears when prices finish loading (37% done).")).toBeInTheDocument();
});

it("keeps exact insufficient copy and explains the completed trade requirement", () => {
  render(<EmptyState reason="insufficient" completedTrades={1} />);
  expect(screen.getByText("Not enough data yet", { exact: true })).toBeInTheDocument();
  expect(screen.getByText("Needs 3+ completed trades (has 1).", { exact: true })).toBeInTheDocument();
});

it("explains unavailable security prices", () => {
  render(<EmptyState reason="not_covered" />);
  expect(screen.getByText("No price data for this security.")).toBeInTheDocument();
});

it("preserves the existing title, description and action interface", () => {
  render(<EmptyState title="No matches" description="Change your filters." action={<button>Clear filters</button>} />);
  expect(screen.getByText("No matches")).toBeInTheDocument();
  expect(screen.getByText("Change your filters.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
});

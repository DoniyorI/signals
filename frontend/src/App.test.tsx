import { render, screen } from "@testing-library/react";
import { AppWithRouter } from "@/App";

it("renders navigation and footer", async () => {
  render(<AppWithRouter initialPath="/" />);
  for (const name of ["Feed", "Screener", "Compare", "Watchlists", "Health"])
    expect(await screen.findByRole("link", { name })).toBeInTheDocument();
  expect(screen.getByText("Data from SEC EDGAR. Not investment advice.")).toBeInTheDocument();
});

it("renders the not-found page for unknown routes", async () => {
  render(<AppWithRouter initialPath="/no/such/page" />);
  expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
});

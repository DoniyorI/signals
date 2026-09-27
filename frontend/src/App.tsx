import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import {
  createBrowserRouter,
  createMemoryRouter,
  type RouteObject,
  RouterProvider,
} from "react-router";
import AppShell from "@/components/layout/AppShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import ComparePage from "@/pages/ComparePage";
import CompanyPage from "@/pages/CompanyPage";
import FeedPage from "@/pages/FeedPage";
import FundPage from "@/pages/FundPage";
import HealthPage from "@/pages/HealthPage";
import InsiderPage from "@/pages/InsiderPage";
import NotFoundPage from "@/pages/NotFoundPage";
import ScreenerPage from "@/pages/ScreenerPage";
import WatchlistsPage from "@/pages/WatchlistsPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <FeedPage /> },
      { path: "insider/:cik", element: <InsiderPage /> },
      { path: "company/:ref", element: <CompanyPage /> },
      { path: "fund/:cik", element: <FundPage /> },
      { path: "screener", element: <ScreenerPage /> },
      { path: "compare", element: <ComparePage /> },
      { path: "watchlists", element: <WatchlistsPage /> },
      { path: "health", element: <HealthPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function makeQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } });
}

/** Test entry point: the full app on an in-memory router. */
export function AppWithRouter({ initialPath = "/" }: { initialPath?: string }) {
  const [client] = useState(makeQueryClient);
  const [router] = useState(() => createMemoryRouter(routes, { initialEntries: [initialPath] }));
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

export default function App() {
  const [client] = useState(makeQueryClient);
  const [router] = useState(() => createBrowserRouter(routes));
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

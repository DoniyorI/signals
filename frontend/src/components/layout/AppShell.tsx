import { Moon, Search, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router";
import { cn } from "@/lib/utils";
import { FreshnessIndicator } from "./FreshnessIndicator";
import { SearchPalette } from "@/components/search/SearchPalette";

const NAV = [
  { to: "/", label: "Feed" },
  { to: "/screener", label: "Screener" },
  { to: "/compare", label: "Compare" },
  { to: "/watchlists", label: "Watchlists" },
  { to: "/health", label: "Health" },
] as const;

type Theme = "light" | "dark";

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem("theme");
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // storage can be unavailable (private mode, blocked site data)
  }
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export default function AppShell() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen((open) => !open);
      }
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem("theme", theme);
    } catch {
      // ignore: the choice just won't persist
    }
  }, [theme]);

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur">
        <nav className="mx-auto flex max-w-[1600px] items-center gap-1 overflow-x-auto px-4 py-2">
          <span className="mr-3 font-semibold tracking-tight">Signals</span>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "rounded-md px-3 py-1.5 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground",
                  isActive && "bg-muted text-foreground",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground"
              data-search-trigger
              onClick={() => setSearchOpen(true)}
            >
              <Search className="size-4" aria-hidden />
              <span className="whitespace-nowrap">Search (⌘K)</span>
            </button>
            <button
              type="button"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              className="rounded-md border p-1.5 text-muted-foreground hover:text-foreground"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
          </div>
        </nav>
        <div className="mx-auto max-w-[1600px] px-4 pb-2"><FreshnessIndicator /></div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
        <Outlet />
      </main>
      <footer className="border-t px-4 py-3 text-xs text-muted-foreground">
        Data from SEC EDGAR. Not investment advice.
      </footer>
      {searchOpen && <SearchPalette open={searchOpen} onOpenChange={setSearchOpen} />}
    </div>
  );
}

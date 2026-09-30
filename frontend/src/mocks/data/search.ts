/** The ⌘K search index: companies, insiders and funds, scored by prefix/substring match. */
import type { Schema } from "@/api/client";
import { insiderProfile, INSIDER_CIKS } from "./insiders";
import { FUNDS, ISSUERS } from "./world";

type SearchHit = Schema<"SearchHit">;
type SearchOut = Schema<"SearchOut">;

function score(name: string, ticker: string | null, q: string): number {
  const n = name.toLowerCase();
  const t = ticker?.toLowerCase() ?? "";
  const needle = q.toLowerCase();
  if (t === needle) return 4;
  if (n.startsWith(needle) || t.startsWith(needle)) return 3;
  if (n.includes(needle)) return 2;
  if (t.includes(needle)) return 1;
  return 0;
}

function topN(hits: SearchHit[], limit: number): SearchHit[] {
  return hits
    .filter((h) => h.score > 0)
    .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
    .slice(0, limit);
}

export function search(q: string, limit = 8): SearchOut {
  const companies = topN(
    ISSUERS.map((i) => ({
      cik: i.ref.cik,
      kind: "company" as const,
      name: i.ref.name,
      score: score(i.ref.name, i.ref.ticker ?? null, q),
      subtitle: i.ref.ticker ? `${i.ref.ticker} · ${i.sector ?? i.exchange}` : i.exchange,
      ticker: i.ref.ticker ?? null,
    })),
    limit,
  );
  const insiders = topN(
    INSIDER_CIKS.map((cik) => {
      const p = insiderProfile(cik)!;
      const role = p.roles[0];
      return {
        cik,
        kind: "insider" as const,
        name: p.owner.name,
        score: score(p.owner.name, null, q),
        subtitle: role ? `${role.roles[0]} · ${role.issuer.name}` : null,
        ticker: null,
      };
    }),
    limit,
  );
  const funds = topN(
    FUNDS.map((f) => ({
      cik: f.cik,
      kind: "fund" as const,
      name: f.name,
      score: score(f.name, null, q),
      subtitle: "13F filer",
      ticker: null,
    })),
    limit,
  );
  return { companies, insiders, funds };
}

/**
 * Company pages: lookup by CIK, current ticker or former ticker; headers with net insider
 * buying derived from decisions; 3 years of bars with markers; roster; 13F holders per
 * quarter; 13D/13G stakes; Form 144 notices.
 */
import type { Schema } from "@/api/client";
import { fmtShares, fmtUsd } from "@/lib/format";
import { FUND_HOLDINGS } from "./funds";
import { FORM144_NOTICES, insiderHeader, insiderProfile, INSIDER_CIKS, issuerDecisions } from "./insiders";
import { addDays, makeBars } from "./series";
import {
  ACME,
  ACME_HOLDINGS,
  AS_OF,
  EXAMPLE_CAPITAL,
  FUNDS,
  issuerInfo,
  ISSUERS,
  type IssuerInfo,
  OLD_CO,
  secUrl,
  SMITH,
} from "./world";

type CompanyHeader = Schema<"CompanyHeader">;
type NetBuying = Schema<"NetBuying">;
type Bar = Schema<"Bar">;
type Marker = Schema<"Marker">;
type InsiderRosterRow = Schema<"InsiderRosterRow">;
type InstitutionsOut = Schema<"InstitutionsOut">;
type InstitutionRow = Schema<"InstitutionRow">;
type StakeOut = Schema<"StakeOut">;

/** An all-digit ref is a CIK; otherwise the current ticker holder, else the latest former holder. */
export function lookupCompany(ref: string): IssuerInfo | undefined {
  if (/^\d+$/.test(ref)) return issuerInfo(Number(ref));
  const symbol = ref.toUpperCase();
  return ISSUERS.find((i) => i.ref.ticker === symbol) ?? ISSUERS.find((i) => i.former.includes(symbol));
}

const WINDOW_DAYS = { "3m": 92, "6m": 183, "12m": 366 } as const;

function netBuying(cik: number, window: keyof typeof WINDOW_DAYS): NetBuying {
  const from = addDays(AS_OF, -WINDOW_DAYS[window]);
  const ds = issuerDecisions(cik).filter((d) => d.plan_10b5_1 === "none" && d.first_trade_date >= from);
  const sum = (dir: string) => ds.filter((d) => d.direction === dir).reduce((s, d) => s + (d.value_usd ?? 0), 0);
  const groups = (dir: string) =>
    new Set(ds.filter((d) => d.direction === dir).map((d) => d.owners.map((o) => o.cik).join(","))).size;
  const buys = sum("buy");
  const sells = sum("sell");
  return {
    window,
    buys_usd: buys,
    sells_usd: sells,
    net_usd: buys - sells,
    n_buyers: groups("buy"),
    n_sellers: groups("sell"),
  };
}

export function companyHeader(info: IssuerInfo): CompanyHeader {
  return {
    cik: info.ref.cik,
    name: info.ref.name,
    ticker: info.ref.ticker ?? null,
    former_tickers: info.former,
    exchange: info.exchange,
    sector: info.sector,
    sic: info.sic,
    sic_description: info.sicDescription,
    market_cap_usd: info.sharesOutstanding * info.lastClose,
    latest_close: info.lastClose,
    latest_close_date: AS_OF,
    net_buying: (["3m", "6m", "12m"] as const).map((w) => netBuying(info.ref.cik, w)),
  };
}

const barsCache = new Map<number, Bar[]>();
function barsOf(info: IssuerInfo): Bar[] {
  let bars = barsCache.get(info.ref.cik);
  if (!bars) {
    bars = makeBars(info.barsFrom, AS_OF, info.lastClose, info.seed);
    barsCache.set(info.ref.cik, bars);
  }
  return bars;
}

export const STAKES: Record<number, StakeOut[]> = {
  [ACME.cik]: [
    {
      accession_no: "0002000003-24-000006",
      sec_url: secUrl(ACME_HOLDINGS.cik, "0002000003-24-000006"),
      form_type: "SCHEDULE 13D",
      filed_date: "2024-05-29",
      event_date: "2024-05-20",
      reporting_persons: [
        { name: ACME_HOLDINGS.name, cik: ACME_HOLDINGS.cik, percent_of_class: 0.123, shares: 30_750_000 },
        { name: SMITH.name, cik: SMITH.cik, percent_of_class: 0.123, shares: 30_750_000 },
      ],
      percent_of_class: 0.123,
      is_activist: true,
      is_current: true,
      purpose_excerpt:
        "The Reporting Persons intend to engage with the Board regarding capital allocation, including a share repurchase program, and may seek board representation.",
    },
    {
      accession_no: "0002000003-23-000019",
      sec_url: secUrl(ACME_HOLDINGS.cik, "0002000003-23-000019"),
      form_type: "SCHEDULE 13D",
      filed_date: "2023-10-02",
      event_date: "2023-09-22",
      reporting_persons: [{ name: ACME_HOLDINGS.name, cik: ACME_HOLDINGS.cik, percent_of_class: 0.101, shares: 25_250_000 }],
      percent_of_class: 0.101,
      is_activist: true,
      is_current: false,
      purpose_excerpt: "The Reporting Persons acquired the shares for investment purposes.",
    },
  ],
  [OLD_CO.cik]: [
    {
      accession_no: "0003000001-24-000009",
      sec_url: secUrl(EXAMPLE_CAPITAL.cik, "0003000001-24-000009"),
      form_type: "SCHEDULE 13G",
      filed_date: "2024-04-12",
      event_date: "2024-03-31",
      reporting_persons: [{ name: EXAMPLE_CAPITAL.name, cik: EXAMPLE_CAPITAL.cik, percent_of_class: 0.061, shares: 4_880_000 }],
      percent_of_class: 0.061,
      is_activist: false,
      is_current: true,
      purpose_excerpt: null,
    },
  ],
};

export function companyStakes(cik: number, currentOnly: boolean): StakeOut[] {
  return (STAKES[cik] ?? []).filter((s) => !currentOnly || s.is_current);
}

export function companyPrices(
  info: IssuerInfo,
  start: string | null,
  end: string | null,
  withMarkers: boolean,
): Schema<"PriceSeriesOut"> {
  const all = barsOf(info);
  const from = start ?? addDays(AS_OF, -3 * 365);
  const to = end ?? AS_OF;
  const bars = all.filter((b) => b.date >= from && b.date <= to);
  if (!withMarkers || bars.length === 0) return { symbol: info.ref.ticker ?? null, bars, markers: [] };
  const [lo, hi] = [bars[0].date, bars[bars.length - 1].date];
  const within = (d: string) => d >= lo && d <= hi;
  const markers: Marker[] = [];
  for (const d of issuerDecisions(info.ref.cik)) {
    if (!within(d.first_trade_date)) continue;
    const who = d.owners.map((o) => o.name).join(", ");
    markers.push({
      date: d.first_trade_date,
      kind: d.direction,
      label: `${d.direction === "buy" ? "Buy" : "Sell"} ${fmtUsd(d.value_usd)} · ${who}`,
      value_usd: d.value_usd,
      ref: d.first_accession,
    });
  }
  for (const n of FORM144_NOTICES.filter((n) => n.issuer.cik === info.ref.cik && within(n.filed_date))) {
    markers.push({
      date: n.filed_date,
      kind: "form144",
      label: `Form 144 · ${n.seller_name} · ${fmtShares(n.shares_to_sell)} sh`,
      value_usd: n.market_value_usd,
      ref: n.accession_no,
    });
  }
  for (const s of companyStakes(info.ref.cik, false)) {
    const date = s.event_date ?? s.filed_date;
    if (!within(date)) continue;
    markers.push({
      date,
      kind: "stake",
      label: `${s.form_type.replace("SCHEDULE ", "")} · ${((s.percent_of_class ?? 0) * 100).toFixed(1)}% · ${s.reporting_persons[0]?.name ?? ""}`,
      value_usd: null,
      ref: s.accession_no,
    });
  }
  if (info.ref.cik === ACME.cik && within("2024-06-04")) {
    markers.push({ date: "2024-06-04", kind: "cluster", label: "Cluster buy · 3 insiders", value_usd: 1_603_500, ref: "cluster:1000001:2024-06-04" });
  }
  markers.sort((a, b) => a.date.localeCompare(b.date));
  return { symbol: info.ref.ticker ?? null, bars, markers };
}

export function companyRoster(cik: number, include: boolean): InsiderRosterRow[] {
  const from = addDays(AS_OF, -366);
  return INSIDER_CIKS.flatMap((ownerCik) => {
    const p = insiderProfile(ownerCik);
    const role = p?.roles.find((r) => r.issuer.cik === cik);
    if (!p || !role) return [];
    const ds = issuerDecisions(cik).filter(
      (d) => d.owners.some((o) => o.cik === ownerCik) && (include || d.plan_10b5_1 === "none"),
    );
    const recent = ds.filter((d) => d.first_trade_date >= from);
    const net = recent.reduce((s, d) => s + (d.direction === "buy" ? 1 : -1) * (d.value_usd ?? 0), 0);
    const last = ds.map((d) => d.first_trade_date).sort().at(-1) ?? null;
    return [
      {
        owner: p.owner,
        roles: role.roles,
        last_trade_date: last,
        net_12m_usd: net,
        n_decisions: ds.length,
        rating: insiderHeader(ownerCik, "filed", include)!.rating,
      },
    ];
  });
}

/** 13F holders of a company per period, derived from the funds' holdings. */
export function companyInstitutions(cik: number, period: string | null): InstitutionsOut {
  const byPeriod = new Map<string, InstitutionRow[]>();
  for (const fund of FUNDS) {
    const periods = FUND_HOLDINGS[fund.cik] ?? {};
    for (const [p, h] of Object.entries(periods)) {
      for (const row of [...h.rows, ...h.exits]) {
        if (row.security.issuer_cik !== cik) continue;
        const list = byPeriod.get(p) ?? [];
        list.push({
          fund,
          shares: row.shares,
          value_usd: row.value_usd,
          weight_in_fund: row.weight,
          change: row.change,
          shares_change_pct: row.shares_change_pct,
          is_tracked: fund.cik === EXAMPLE_CAPITAL.cik,
        });
        byPeriod.set(p, list);
      }
    }
  }
  const periods = [...byPeriod.keys()].sort().reverse();
  const chosen = period ?? periods[0] ?? null;
  const all = chosen ? (byPeriod.get(chosen) ?? []) : [];
  const rows = all.filter((r) => r.change !== "EXIT").sort((a, b) => b.value_usd - a.value_usd);
  return {
    period: chosen,
    periods_available: periods,
    rows,
    total_value_usd: rows.reduce((s, r) => s + r.value_usd, 0),
    holders_count: rows.length,
    new_count: rows.filter((r) => r.change === "NEW").length,
    exit_count: all.filter((r) => r.change === "EXIT").length,
    next_cursor: null,
  };
}

export function companyForm144(cik: number, status: string | null): Schema<"Form144Out">[] {
  return FORM144_NOTICES.filter((n) => n.issuer.cik === cik && (!status || n.status === status));
}

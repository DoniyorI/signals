/**
 * Insider profiles. Decisions carry filed-basis 6m excess returns; every header metric
 * (Avg ROI, hit rate, median, best/worst, lag) is derived from them, so a profile's
 * numbers agree with its own decisions table. Doe Jane (2000001) is rated 78 · High,
 * Roe Richard (2000002) 54 · Medium; everyone else has no stats, as in the seed world.
 */
import type { Schema } from "@/api/client";
import { addDays, makeCurve, windowsFromCurve } from "./series";
import {
  ACME,
  ACME_HOLDINGS,
  AS_OF,
  AS_OF_CLOSE,
  CODE_LABELS,
  DOE,
  GLOBEX,
  NEW_CO,
  NEW_PERSON,
  ROE,
  secUrl,
  SMITH,
} from "./world";

type Basis = "filed" | "executed";
type DecisionOut = Schema<"DecisionOut">;
type HorizonReturn = Schema<"HorizonReturn">;
type InsiderHeader = Schema<"InsiderHeader">;
type IssuerRef = Schema<"IssuerRef">;
type OwnerRef = Schema<"OwnerRef">;
type TransactionOut = Schema<"TransactionOut">;
type HoldingsOut = Schema<"HoldingsOut">;
type Form144Out = Schema<"Form144Out">;
type PerformanceOut = Schema<"PerformanceOut">;
type RoleAtIssuer = Schema<"RoleAtIssuer">;
type Rating = Schema<"Rating">;

interface DecisionSpec {
  id: number;
  issuer: IssuerRef;
  owners: OwnerRef[];
  dir: "buy" | "sell";
  first: string;
  shares: number;
  vwap: number;
  stake?: number | null;
  plan?: "flag" | "footnote" | "none";
  badges?: string[];
  lag: number;
  lagCost: number;
  /** Filed-basis 6m excess return vs SPY (sales already sign-flipped). */
  e6: number;
}

const HORIZONS = [
  { h: "1m", days: 31, k: 0.25, spy: 0.011 },
  { h: "3m", days: 92, k: 0.6, spy: 0.029 },
  { h: "6m", days: 183, k: 1.0, spy: 0.057 },
  { h: "12m", days: 366, k: 1.45, spy: 0.101 },
] as const;

const r4 = (x: number) => Math.round(x * 10_000) / 10_000;

function returnsFor(d: DecisionSpec, basis: Basis): HorizonReturn[] {
  const shift = basis === "executed" ? d.lagCost : 0;
  return HORIZONS.map(({ h, days, k, spy }) => {
    if (addDays(d.first, days) > AS_OF) {
      return { horizon: h, raw: null, excess_spy: null, excess_qqq: null, excess_sector: null, complete: false };
    }
    const ex = d.e6 * k + shift;
    return {
      horizon: h,
      raw: r4(d.dir === "buy" ? ex + spy : ex - spy),
      excess_spy: r4(ex),
      excess_qqq: r4(ex - 0.006 * k),
      excess_sector: r4(ex - 0.003 * k),
      complete: true,
    };
  });
}

function accessionOf(d: DecisionSpec): string {
  return `${String(d.owners[0].cik).padStart(10, "0")}-${d.first.slice(2, 4)}-${String(d.id).padStart(6, "0")}`;
}

function acceptedOf(d: DecisionSpec): string {
  return `${addDays(d.first, d.lag)}T20:30:00Z`;
}

function toDecision(d: DecisionSpec, basis: Basis): DecisionOut {
  const acc = accessionOf(d);
  return {
    id: d.id,
    issuer: d.issuer,
    owners: d.owners,
    direction: d.dir,
    first_trade_date: d.first,
    last_trade_date: d.first,
    shares: d.shares,
    value_usd: Math.round(d.shares * d.vwap * 100) / 100,
    vwap: d.vwap,
    stake_change_pct: d.stake ?? null,
    accepted_at: acceptedOf(d),
    plan_10b5_1: d.plan ?? "none",
    badges: d.badges ?? [],
    lag_days: d.lag,
    lag_cost: d.lagCost,
    returns: returnsFor(d, basis),
    first_accession: acc,
    sec_url: secUrl(d.owners[0].cik, acc),
  };
}

const DOE_TOP = ["top_exec"];
let nextId = 101;
function doe(first: string, dir: "buy" | "sell", e6: number, extra: Partial<DecisionSpec> = {}): DecisionSpec {
  const id = nextId++;
  return {
    id,
    issuer: ACME,
    owners: [DOE],
    dir,
    first,
    shares: 2_000 + (id % 4) * 1_500,
    vwap: 4 + ((id * 7) % 60) / 10,
    stake: dir === "buy" ? 0.04 + (id % 5) * 0.03 : null,
    lag: 1 + (id % 2),
    lagCost: 0.003 + (id % 4) * 0.004,
    badges: DOE_TOP,
    e6,
    ...extra,
  };
}

const DOE_DECISIONS: DecisionSpec[] = [
  doe("2024-06-05", "buy", 0, {
    shares: 5_000,
    vwap: 9.8,
    stake: 0.833,
    lag: 2,
    lagCost: 0.004,
    badges: ["cluster_buy", "big_stake", "top_exec"],
  }),
  doe("2024-02-26", "buy", 0.061),
  doe("2023-11-14", "buy", 0.142, { badges: ["dip_buy", "top_exec"] }),
  doe("2023-08-10", "sell", 0.02, { plan: "flag" }),
  doe("2023-03-20", "buy", 0.098),
  doe("2022-09-12", "sell", 0.064),
  doe("2022-05-18", "buy", -0.052, { badges: ["dip_buy", "top_exec"] }),
  doe("2021-11-03", "buy", -0.118),
  doe("2021-05-10", "buy", 0.035),
  doe("2020-11-16", "sell", 0.021),
  doe("2020-03-23", "buy", 0.412, { badges: ["dip_buy", "big_stake", "top_exec"], stake: 0.31 }),
  doe("2019-12-02", "buy", 0.155),
  doe("2019-08-15", "buy", 0.071),
  doe("2019-03-04", "sell", -0.024),
  doe("2018-10-29", "buy", 0.188),
  doe("2018-06-11", "buy", -0.041),
  doe("2018-02-12", "buy", 0.093),
  doe("2017-09-05", "sell", -0.066),
  doe("2017-05-22", "buy", 0.117),
  doe("2016-12-12", "buy", 0.052),
  doe("2016-06-27", "buy", -0.009, { badges: ["first_buy_2y", "top_exec"] }),
];

function roe(
  id: number,
  issuer: IssuerRef,
  first: string,
  dir: "buy" | "sell",
  e6: number,
  extra: Partial<DecisionSpec> = {},
): DecisionSpec {
  return {
    id,
    issuer,
    owners: [ROE],
    dir,
    first,
    shares: 3_000 + (id % 3) * 2_000,
    vwap: issuer.cik === GLOBEX.cik ? 30 + (id % 9) : 5 + (id % 5),
    stake: dir === "buy" ? 0.05 + (id % 4) * 0.02 : null,
    lag: 1 + (id % 3),
    lagCost: 0.002 + (id % 3) * 0.003,
    e6,
    ...extra,
  };
}

const ROE_DECISIONS: DecisionSpec[] = [
  roe(201, ACME, "2024-06-05", "buy", 0, { shares: 10_000, vwap: 9.95, badges: ["cluster_buy"], lag: 1 }),
  roe(202, GLOBEX, "2024-06-03", "sell", 0.01, {
    shares: 8_000,
    vwap: 42.1,
    plan: "flag",
    badges: ["form144_matched"],
    lag: 1,
  }),
  roe(203, GLOBEX, "2023-11-27", "buy", 0.044),
  roe(204, ACME, "2023-06-05", "buy", -0.031),
  roe(205, GLOBEX, "2022-10-17", "sell", 0.027),
  roe(206, ACME, "2022-03-14", "buy", 0.081),
  roe(207, GLOBEX, "2021-09-20", "buy", -0.012, { lag: 4, badges: ["late_filing"] }),
  roe(208, ACME, "2021-04-12", "buy", 0.036),
  roe(209, ACME, "2020-10-05", "sell", 0.006),
];

const GROUP_DECISIONS: DecisionSpec[] = [
  {
    id: 301,
    issuer: ACME,
    owners: [ACME_HOLDINGS, SMITH],
    dir: "buy",
    first: "2024-06-04",
    shares: 150_000,
    vwap: 9.7,
    stake: 0.052,
    badges: ["cluster_buy", "big_stake"],
    lag: 1,
    lagCost: 0.006,
    e6: 0,
  },
  {
    id: 302,
    issuer: ACME,
    owners: [ACME_HOLDINGS, SMITH],
    dir: "buy",
    first: "2024-01-22",
    shares: 120_000,
    vwap: 8.6,
    stake: 0.045,
    badges: ["big_stake"],
    lag: 1,
    lagCost: 0.005,
    e6: 0.02,
  },
];

const NEW_PERSON_DECISIONS: DecisionSpec[] = [
  {
    id: 501,
    issuer: NEW_CO,
    owners: [NEW_PERSON],
    dir: "buy",
    first: "2024-05-16",
    shares: 2_000,
    vwap: 15.25,
    stake: null,
    badges: ["first_buy_2y"],
    lag: 2,
    lagCost: 0.011,
    e6: 0,
  },
];

const ALL_DECISIONS = [...DOE_DECISIONS, ...ROE_DECISIONS, ...GROUP_DECISIONS, ...NEW_PERSON_DECISIONS];

function decisionsOf(cik: number): DecisionSpec[] {
  return ALL_DECISIONS.filter((d) => d.owners.some((o) => o.cik === cik));
}

interface Profile {
  owner: OwnerRef;
  ownerType: "person" | "entity";
  roles: RoleAtIssuer[];
  /** Null when the seed world has no profile_stats row for this insider. */
  rating: { score: number; confidence: "low" | "medium" | "high"; risk: "low" | "medium" | "high" } | null;
  curveFrom: string | null;
  drift: number;
}

const PROFILES: Profile[] = [
  {
    owner: DOE,
    ownerType: "person",
    roles: [
      {
        issuer: ACME,
        roles: ["CEO", "Director"],
        officer_title: "Chief Executive Officer",
        first_filed: "2016-03-01",
        last_filed: "2024-06-07",
      },
    ],
    rating: { score: 78, confidence: "high", risk: "medium" },
    curveFrom: "2019-06-07",
    drift: 0.00062,
  },
  {
    owner: ROE,
    ownerType: "person",
    roles: [
      { issuer: ACME, roles: ["Director"], officer_title: null, first_filed: "2017-05-15", last_filed: "2024-06-06" },
      { issuer: GLOBEX, roles: ["Director"], officer_title: null, first_filed: "2019-02-11", last_filed: "2024-06-04" },
    ],
    rating: { score: 54, confidence: "medium", risk: "low" },
    curveFrom: "2020-10-05",
    drift: 0.00046,
  },
  {
    owner: ACME_HOLDINGS,
    ownerType: "entity",
    roles: [{ issuer: ACME, roles: ["10% owner"], officer_title: null, first_filed: "2021-08-02", last_filed: "2024-06-05" }],
    rating: null,
    curveFrom: null,
    drift: 0,
  },
  {
    owner: SMITH,
    ownerType: "person",
    roles: [{ issuer: ACME, roles: ["10% owner"], officer_title: null, first_filed: "2021-08-02", last_filed: "2024-06-05" }],
    rating: null,
    curveFrom: null,
    drift: 0,
  },
  {
    owner: NEW_PERSON,
    ownerType: "person",
    roles: [{ issuer: NEW_CO, roles: ["Director"], officer_title: null, first_filed: "2024-04-26", last_filed: "2024-05-20" }],
    rating: null,
    curveFrom: null,
    drift: 0,
  },
];

export function insiderProfile(cik: number): Profile | undefined {
  return PROFILES.find((p) => p.owner.cik === cik);
}

export const INSIDER_CIKS = PROFILES.map((p) => p.owner.cik);

function visible(ds: DecisionSpec[], include: boolean): DecisionSpec[] {
  return ds.filter((d) => include || (d.plan ?? "none") === "none");
}

const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
const maybe = (x: number | null) => (x === null ? null : r4(x));

export function insiderHeader(cik: number, basis: Basis, include: boolean): InsiderHeader | undefined {
  const p = insiderProfile(cik);
  if (!p) return undefined;
  const ds = visible(decisionsOf(cik), include);
  const decisions = ds.map((d) => toDecision(d, basis));
  const complete = decisions.filter((d) => d.returns[2].complete);
  const ex6 = complete.map((d) => d.returns[2].excess_spy ?? 0);
  const raw6 = complete.map((d) => d.returns[2].raw ?? 0);
  const counts = {
    n_decisions: ds.length,
    n_buys: ds.filter((d) => d.dir === "buy").length,
    n_sells: ds.filter((d) => d.dir === "sell").length,
  };
  const noStats: Rating = { score: null, confidence: null, n: 0 };
  const header: InsiderHeader = {
    cik,
    name: p.owner.name,
    owner_type: p.ownerType,
    roles: p.roles,
    basis,
    include_10b5_1: include,
    rating: noStats,
    avg_roi_6m: null,
    avg_roi_6m_raw: null,
    median_6m: null,
    hit_rate: null,
    ...counts,
    avg_lag_days: null,
    avg_lag_cost: null,
    best: null,
    worst: null,
    risk_label: null,
    fund_cik: null,
    updated_at: null,
  };
  if (!p.rating) return header;
  const byEx = [...complete].sort((a, b) => (b.returns[2].excess_spy ?? 0) - (a.returns[2].excess_spy ?? 0));
  return {
    ...header,
    rating: { score: p.rating.score, confidence: p.rating.confidence, n: complete.length },
    avg_roi_6m: maybe(mean(ex6)),
    avg_roi_6m_raw: maybe(mean(raw6)),
    median_6m: maybe(median(ex6)),
    hit_rate: complete.length ? r4(ex6.filter((x) => x > 0).length / complete.length) : null,
    avg_lag_days: maybe(mean(ds.map((d) => d.lag))),
    avg_lag_cost: maybe(mean(ds.map((d) => d.lagCost))),
    best: byEx[0] ?? null,
    worst: byEx[byEx.length - 1] ?? null,
    risk_label: p.rating.risk,
    updated_at: "2024-06-08T06:12:00Z",
  };
}

export function insiderDecisions(
  cik: number,
  basis: Basis,
  include: boolean,
  direction: string | null,
): DecisionOut[] {
  return visible(decisionsOf(cik), include)
    .filter((d) => !direction || d.dir === direction)
    .sort((a, b) => b.first.localeCompare(a.first) || b.id - a.id)
    .map((d) => toDecision(d, basis));
}

/** All decisions of an issuer (for company price markers and net buying). */
export function issuerDecisions(issuerCik: number): DecisionOut[] {
  return ALL_DECISIONS.filter((d) => d.issuer.cik === issuerCik).map((d) => toDecision(d, "filed"));
}

function txRow(
  d: {
    acc: string;
    owner: number;
    issuer: IssuerRef;
    date: string;
    code: string;
    ad: "A" | "D";
    shares: number;
    price: number | null;
    after: number | null;
    title?: string;
    kind?: "nonderiv" | "deriv";
    plan?: "flag" | "footnote" | "none";
    superseded?: boolean;
    footnotes?: string[];
    form?: string;
  },
): TransactionOut {
  return {
    accession_no: d.acc,
    sec_url: secUrl(d.owner, d.acc),
    form_type: d.form ?? "4",
    accepted_at: `${addDays(d.date, 2)}T20:30:00Z`,
    issuer: d.issuer,
    transaction_date: d.date,
    code: d.code,
    code_label: CODE_LABELS[d.code] ?? null,
    acquired_disposed: d.ad,
    shares: d.shares,
    price: d.price,
    value_usd: d.price === null ? null : Math.round(d.shares * d.price * 100) / 100,
    shares_owned_after: d.after,
    direct_indirect: "D",
    security_title: d.title ?? "Common Stock",
    table_kind: d.kind ?? "nonderiv",
    plan_10b5_1: d.plan ?? "none",
    superseded: d.superseded ?? false,
    footnotes: d.footnotes ?? [],
  };
}

const PLAN_FOOTNOTE =
  "The reported transaction was effected pursuant to a Rule 10b5-1 trading plan adopted on March 1, 2023.";

function transactionsFor(cik: number): TransactionOut[] {
  const fromDecisions = decisionsOf(cik).map((d) =>
    txRow({
      acc: accessionOf(d),
      owner: d.owners[0].cik,
      issuer: d.issuer,
      date: d.first,
      code: d.dir === "buy" ? "P" : "S",
      ad: d.dir === "buy" ? "A" : "D",
      shares: d.shares,
      price: d.vwap,
      after: null,
      plan: d.plan ?? "none",
      footnotes: d.plan && d.plan !== "none" ? [PLAN_FOOTNOTE] : [],
    }),
  );
  const extras: TransactionOut[] =
    cik === DOE.cik
      ? [
          txRow({ acc: "0002000001-24-000004", owner: DOE.cik, issuer: ACME, date: "2024-02-15", code: "A", ad: "A", shares: 20_000, price: 0, after: 31_000, title: "Restricted Stock Units", footnotes: ["Vests in four equal annual installments."] }),
          txRow({ acc: "0002000001-23-000041", owner: DOE.cik, issuer: ACME, date: "2023-08-10", code: "M", ad: "A", shares: 8_000, price: 4.25, after: 8_000, title: "Stock Option (right to buy)", kind: "deriv" }),
          txRow({ acc: "0002000001-23-000041", owner: DOE.cik, issuer: ACME, date: "2023-08-10", code: "F", ad: "D", shares: 3_100, price: 8.4, after: 12_900, footnotes: ["Shares withheld to cover taxes on the option exercise."] }),
          txRow({ acc: "0002000001-22-000077", owner: DOE.cik, issuer: ACME, date: "2022-12-20", code: "G", ad: "D", shares: 1_000, price: null, after: 9_000, form: "5" }),
          txRow({ acc: "0002000001-23-000019", owner: DOE.cik, issuer: ACME, date: "2023-03-20", code: "P", ad: "A", shares: 4_500, price: 6.2, after: 10_500, superseded: true, footnotes: ["Superseded by the Form 4/A filed on 2023-03-24."] }),
        ]
      : [];
  return [...fromDecisions, ...extras].sort(
    (a, b) =>
      (b.transaction_date ?? "").localeCompare(a.transaction_date ?? "") ||
      b.accession_no.localeCompare(a.accession_no),
  );
}

export function insiderTransactions(cik: number, includeSuperseded: boolean): TransactionOut[] {
  return transactionsFor(cik).filter((t) => includeSuperseded || !t.superseded);
}

function holding(issuer: IssuerRef, sector: string, shares: number, close: number, weight: number) {
  return {
    issuer,
    security_title: "Common Stock",
    shares,
    value_usd: shares * close,
    weight,
    sector,
    direct_indirect: "D",
    as_of_date: AS_OF,
  };
}

export function insiderHoldings(cik: number): HoldingsOut {
  const empty: HoldingsOut = {
    positions: [],
    derivatives: [],
    by_sector: [],
    by_issuer: [],
    effective_n: null,
    top5_weight: null,
    total_value_usd: null,
  };
  if (cik === DOE.cik) {
    const acme = holding(ACME, "Technology", 11_000, AS_OF_CLOSE.ACME, 1);
    return {
      positions: [acme],
      derivatives: [
        {
          issuer: ACME,
          security_title: "Stock Option (right to buy)",
          shares: 40_000,
          value_usd: null,
          weight: null,
          sector: "Technology",
          direct_indirect: "D",
          as_of_date: "2024-02-15",
        },
      ],
      by_sector: [{ key: "Technology", label: "Technology", value_usd: acme.value_usd, weight: 1 }],
      by_issuer: [{ key: String(ACME.cik), label: ACME.name, value_usd: acme.value_usd, weight: 1 }],
      effective_n: 1.0,
      top5_weight: 1.0,
      total_value_usd: acme.value_usd,
    };
  }
  if (cik === ROE.cik) {
    const a = 20_000 * AS_OF_CLOSE.ACME;
    const g = 6_000 * AS_OF_CLOSE.GLBX;
    const t = a + g;
    return {
      positions: [
        holding(GLOBEX, "Communication Services", 6_000, AS_OF_CLOSE.GLBX, r4(g / t)),
        holding(ACME, "Technology", 20_000, AS_OF_CLOSE.ACME, r4(a / t)),
      ],
      derivatives: [],
      by_sector: [
        { key: "Communication Services", label: "Communication Services", value_usd: g, weight: r4(g / t) },
        { key: "Technology", label: "Technology", value_usd: a, weight: r4(a / t) },
      ],
      by_issuer: [
        { key: String(GLOBEX.cik), label: GLOBEX.name, value_usd: g, weight: r4(g / t) },
        { key: String(ACME.cik), label: ACME.name, value_usd: a, weight: r4(a / t) },
      ],
      effective_n: r4(1 / ((g / t) ** 2 + (a / t) ** 2)),
      top5_weight: 1,
      total_value_usd: t,
    };
  }
  if (cik === NEW_PERSON.cik) {
    const v = 2_000 * AS_OF_CLOSE.XYZ;
    return {
      ...empty,
      positions: [holding(NEW_CO, "Health Care", 2_000, AS_OF_CLOSE.XYZ, 1)],
      by_sector: [{ key: "Health Care", label: "Health Care", value_usd: v, weight: 1 }],
      by_issuer: [{ key: String(NEW_CO.cik), label: NEW_CO.name, value_usd: v, weight: 1 }],
      effective_n: 1,
      top5_weight: 1,
      total_value_usd: v,
    };
  }
  return empty;
}

export const FORM144_NOTICES: Form144Out[] = [
  {
    accession_no: "0002000002-24-000033",
    sec_url: secUrl(ROE.cik, "0002000002-24-000033"),
    filed_date: "2024-06-06",
    issuer: ACME,
    seller_name: "Roe Richard",
    relationship: "Director",
    shares_to_sell: 5_000,
    market_value_usd: 49_750,
    approx_sale_date: "2024-06-20",
    broker: "Fidelity Brokerage Services LLC",
    plan_10b5_1_adopted: null,
    matched_sale_accession: null,
    status: "pending",
  },
  {
    accession_no: "0002000002-24-000028",
    sec_url: secUrl(ROE.cik, "0002000002-24-000028"),
    filed_date: "2024-06-03",
    issuer: GLOBEX,
    seller_name: "Roe Richard",
    relationship: "Director",
    shares_to_sell: 8_000,
    market_value_usd: 340_000,
    approx_sale_date: "2024-06-03",
    broker: "Morgan Stanley Smith Barney LLC",
    plan_10b5_1_adopted: "2024-02-12",
    matched_sale_accession: "0002000002-24-000029",
    status: "matched",
  },
];

export function insiderForm144(cik: number): Form144Out[] {
  return cik === ROE.cik ? FORM144_NOTICES : [];
}

const SEEDS: Record<string, number> = { filed: 7, executed: 8 };

export function insiderPerformance(cik: number, basis: Basis, include: boolean): PerformanceOut {
  const p = insiderProfile(cik);
  if (!p || !p.curveFrom) {
    return { basis, points: [], windows: windowsFromCurve([]), coverage_pct: null, as_of: AS_OF };
  }
  const boost = (basis === "executed" ? 0.00008 : 0) - (include ? 0.00003 : 0);
  const points = makeCurve(
    p.curveFrom,
    AS_OF,
    { nav: p.drift + boost, spy: 0.00045, qqq: 0.00056, sector: 0.0005 },
    cik + SEEDS[basis] * 100 + (include ? 1 : 0),
  );
  return { basis, points, windows: windowsFromCurve(points), coverage_pct: null, as_of: AS_OF };
}

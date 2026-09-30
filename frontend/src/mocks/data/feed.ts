/**
 * Feed items: the six seed-world filings (2024-06-03 .. 2024-06-07), then a generated
 * history of older filings so the feed has more than one page even with 10b5-1 hidden.
 */
import type { Schema } from "@/api/client";
import { formFamily } from "@/lib/domain";
import { businessDays } from "./series";
import {
  ACME,
  ACME_HOLDINGS,
  DOE,
  EXAMPLE_CAPITAL,
  GLOBEX,
  issuerInfo,
  marketCap,
  NEW_CO,
  NEW_PERSON,
  OLD_CO,
  QUIET_HARBOR,
  ROE,
  secUrl,
  SMITH,
} from "./world";

type FeedItem = Schema<"FeedItemOut">;
type IssuerRef = Schema<"IssuerRef">;
type OwnerRef = Schema<"OwnerRef">;

const etDate = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" });

function shares(n: number): string {
  return Number.isInteger(n)
    ? n.toLocaleString("en-US")
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Mirrors the backend's `summarize_trade`: 'Bought 12,000 sh @ $41.25 ($495,000)'. */
export function summarizeTrade(
  direction: string,
  sh: number | null,
  price: number | null,
  value: number | null,
): string {
  const verb = direction === "buy" ? "Bought" : direction === "sell" ? "Sold" : "Reported";
  const parts = [verb];
  if (sh !== null) parts.push(`${shares(sh)} sh`);
  if (price !== null) parts.push(`@ $${price.toFixed(2)}`);
  if (value !== null) parts.push(`($${Math.round(value).toLocaleString("en-US")})`);
  return parts.join(" ");
}

interface Spec {
  acc: string;
  form: string;
  at: string;
  issuer: IssuerRef | null;
  owners: OwnerRef[];
  role?: string | null;
  dir?: FeedItem["direction"];
  codes?: string[];
  shares?: number | null;
  price?: number | null;
  value?: number | null;
  plan?: FeedItem["plan_10b5_1"];
  badges?: string[];
  lag?: number | null;
  summary?: string;
}

function feedItem(s: Spec): FeedItem {
  const sh = s.shares ?? null;
  const price = s.price ?? null;
  const value = s.value ?? (sh !== null && price !== null ? Math.round(sh * price * 100) / 100 : null);
  const dir = s.dir ?? null;
  const info = s.issuer ? issuerInfo(s.issuer.cik) : undefined;
  return {
    accession_no: s.acc,
    sec_url: secUrl(s.owners[0]?.cik ?? s.issuer?.cik ?? 0, s.acc),
    form_type: s.form,
    accepted_at: s.at,
    filed_date: etDate.format(new Date(s.at)),
    issuer: s.issuer,
    owners: s.owners,
    top_role: s.role ?? null,
    direction: dir,
    codes: s.codes ?? [],
    value_usd: value,
    shares: sh,
    price,
    plan_10b5_1: s.plan === undefined ? "none" : s.plan,
    badges: s.badges ?? [],
    market_cap_usd: s.issuer ? marketCap(s.issuer.cik) : null,
    sector: info?.sector ?? null,
    summary: s.summary ?? summarizeTrade(dir ?? "other", sh, price, value),
    lag_days: s.lag === undefined ? null : s.lag,
  };
}

/** The six filings of the API seed world, newest first. */
export const SEED_FEED: FeedItem[] = [
  feedItem({
    acc: "0002000001-24-000012",
    form: "4",
    at: "2024-06-07T20:05:12Z",
    issuer: ACME,
    owners: [DOE],
    role: "CEO",
    dir: "buy",
    codes: ["P"],
    shares: 5_000,
    price: 9.8,
    badges: ["cluster_buy", "big_stake", "top_exec"],
    lag: 2,
  }),
  feedItem({
    acc: "0002000002-24-000031",
    form: "4",
    at: "2024-06-06T21:40:03Z",
    issuer: ACME,
    owners: [ROE],
    role: "Director",
    dir: "buy",
    codes: ["P"],
    shares: 10_000,
    price: 9.95,
    badges: ["cluster_buy"],
    lag: 1,
  }),
  feedItem({
    acc: "0002000003-24-000008",
    form: "4",
    at: "2024-06-05T14:02:31Z",
    issuer: ACME,
    owners: [ACME_HOLDINGS, SMITH],
    role: "10% owner",
    dir: "buy",
    codes: ["P"],
    shares: 150_000,
    price: 9.7,
    badges: ["cluster_buy", "big_stake"],
    lag: 1,
  }),
  feedItem({
    acc: "0002000002-24-000029",
    form: "4",
    at: "2024-06-04T22:15:09Z",
    issuer: GLOBEX,
    owners: [ROE],
    role: "Director",
    dir: "sell",
    codes: ["S"],
    shares: 8_000,
    price: 42.1,
    plan: "flag",
    badges: ["form144_matched"],
    lag: 1,
  }),
  feedItem({
    acc: "0003000001-24-000004",
    form: "13F-HR",
    at: "2024-06-03T19:12:44Z",
    issuer: null,
    owners: [EXAMPLE_CAPITAL],
    value: 38_200_000,
    plan: null,
    summary: "13F-HR for Mar 31, 2024: 2 positions, $38.2M",
  }),
  feedItem({
    acc: "0002000002-24-000028",
    form: "144",
    at: "2024-06-03T13:20:00Z",
    issuer: GLOBEX,
    owners: [ROE],
    role: "Director",
    shares: 8_000,
    value: 340_000,
    plan: null,
    summary: "Proposed sale of 8,000 sh ($340,000) through Morgan Stanley",
  }),
];

/** Older filings: two per business day, back from 2024-05-31. */
function history(): FeedItem[] {
  const days = businessDays("2024-04-01", "2024-05-31").reverse();
  const out: FeedItem[] = [];
  let seq = 100;
  const acmePx = (i: number) => Math.round((9.1 + ((i * 7) % 9) / 10) * 100) / 100;
  const gbxPx = (i: number) => Math.round((40.8 + ((i * 5) % 7) * 0.3) * 100) / 100;
  for (let i = 0; i < 64; i++) {
    const day = days[Math.floor(i / 2)];
    const at = `${day}T${i % 2 === 0 ? "21:35:07" : "14:10:42"}Z`;
    const acc = (cik: number) => `${String(cik).padStart(10, "0")}-24-${String(seq++).padStart(6, "0")}`;
    const oneOff: Record<number, () => FeedItem> = {
      11: () =>
        feedItem({
          acc: acc(NEW_PERSON.cik),
          form: "4",
          at,
          issuer: NEW_CO,
          owners: [NEW_PERSON],
          role: "Director",
          dir: "buy",
          codes: ["P"],
          shares: 2_000,
          price: 15.25,
          badges: ["first_buy_2y"],
          lag: 2,
        }),
      17: () =>
        feedItem({
          acc: acc(QUIET_HARBOR.cik),
          form: "13F-HR",
          at,
          issuer: null,
          owners: [QUIET_HARBOR],
          value: 3_100_000,
          plan: null,
          summary: "13F-HR for Mar 31, 2024: 1 position, $3.1M",
        }),
      25: () =>
        feedItem({
          acc: acc(NEW_PERSON.cik),
          form: "3",
          at,
          issuer: NEW_CO,
          owners: [NEW_PERSON],
          role: "Director",
          plan: null,
          summary: "Initial statement: no shares held",
        }),
      33: () =>
        feedItem({
          acc: acc(SMITH.cik),
          form: "5",
          at,
          issuer: ACME,
          owners: [SMITH],
          role: "10% owner",
          dir: "other",
          codes: ["G"],
          shares: 12_000,
          summary: "Annual statement: gifted 12,000 sh",
        }),
      41: () =>
        feedItem({
          acc: acc(ROE.cik),
          form: "4/A",
          at,
          issuer: GLOBEX,
          owners: [ROE],
          role: "Director",
          dir: "buy",
          codes: ["P"],
          shares: 1_500,
          price: gbxPx(i),
          lag: 3,
          badges: ["late_filing"],
        }),
      50: () =>
        feedItem({
          acc: acc(EXAMPLE_CAPITAL.cik),
          form: "SCHEDULE 13G",
          at,
          issuer: OLD_CO,
          owners: [EXAMPLE_CAPITAL],
          plan: null,
          summary: "Passive stake: 6.1% of class",
        }),
    };
    if (oneOff[i]) {
      out.push(oneOff[i]());
      continue;
    }
    const recurring: Array<() => FeedItem> = [
      () =>
        feedItem({
          acc: acc(DOE.cik),
          form: "4",
          at,
          issuer: ACME,
          owners: [DOE],
          role: "CEO",
          dir: "buy",
          codes: ["P"],
          shares: 2_000 + ((i * 37) % 5) * 1_000,
          price: acmePx(i),
          badges: ["top_exec"],
          lag: 2,
        }),
      () =>
        feedItem({
          acc: acc(ROE.cik),
          form: "4",
          at,
          issuer: GLOBEX,
          owners: [ROE],
          role: "Director",
          dir: "sell",
          codes: ["S"],
          shares: 3_000,
          price: gbxPx(i),
          plan: "flag",
          lag: 2,
        }),
      () =>
        feedItem({
          acc: acc(DOE.cik),
          form: "4",
          at,
          issuer: ACME,
          owners: [DOE],
          role: "CEO",
          dir: "other",
          codes: ["M", "F"],
          shares: 8_000,
          price: 4.25,
          lag: 2,
          summary: "Exercised 8,000 options @ $4.25; 3,100 sh withheld for taxes",
        }),
      () =>
        feedItem({
          acc: acc(ROE.cik),
          form: "4",
          at,
          issuer: ACME,
          owners: [ROE],
          role: "Director",
          dir: "buy",
          codes: ["P"],
          shares: 4_000,
          price: acmePx(i),
          lag: i % 3 === 0 ? 4 : 1,
          badges: i % 3 === 0 ? ["late_filing"] : [],
        }),
      () =>
        feedItem({
          acc: acc(ROE.cik),
          form: "144",
          at,
          issuer: i % 2 === 0 ? ACME : GLOBEX,
          owners: [ROE],
          role: "Director",
          shares: 5_000,
          value: i % 2 === 0 ? 48_500 : 212_500,
          plan: null,
          summary: `Proposed sale of 5,000 sh (${i % 2 === 0 ? "$48,500" : "$212,500"})`,
        }),
      () =>
        feedItem({
          acc: acc(ACME_HOLDINGS.cik),
          form: "4",
          at,
          issuer: ACME,
          owners: [ACME_HOLDINGS, SMITH],
          role: "10% owner",
          dir: "buy",
          codes: ["P"],
          shares: 60_000 + ((i * 13) % 4) * 30_000,
          price: acmePx(i),
          lag: 1,
          badges: ["big_stake"],
        }),
      () =>
        feedItem({
          acc: acc(DOE.cik),
          form: "4",
          at,
          issuer: ACME,
          owners: [DOE],
          role: "CEO",
          dir: "sell",
          codes: ["S"],
          shares: 6_000,
          price: acmePx(i),
          plan: "footnote",
          lag: 2,
        }),
      () =>
        feedItem({
          acc: acc(ACME_HOLDINGS.cik),
          form: "SCHEDULE 13D/A",
          at,
          issuer: ACME,
          owners: [ACME_HOLDINGS, SMITH],
          plan: null,
          summary: "Activist stake amended: 12.3% of class",
        }),
    ];
    out.push(recurring[i % recurring.length]());
  }
  return out;
}

export const FEED: FeedItem[] = [...SEED_FEED, ...history()].sort((a, b) =>
  (b.accepted_at ?? "").localeCompare(a.accepted_at ?? "") || b.accession_no.localeCompare(a.accession_no),
);

/** Applies `/api/feed` query filters the way the API does (plan 06, Task E2). */
export function filterFeed(items: FeedItem[], sp: URLSearchParams): FeedItem[] {
  const list = (k: string) => sp.getAll(k).filter(Boolean);
  const num = (k: string) => (sp.get(k) ? Number(sp.get(k)) : null);
  const forms = list("forms");
  const directions = list("direction");
  const codes = list("codes");
  const roles = list("roles");
  const sectors = list("sectors");
  const badges = list("badges");
  const [minV, maxV, minM, maxM, maxLag] = [
    num("min_value"),
    num("max_value"),
    num("min_mcap"),
    num("max_mcap"),
    num("max_lag_days"),
  ];
  const issuerCik = num("issuer_cik");
  const ownerCik = num("owner_cik");
  const include = sp.get("include_10b5_1") !== "false";
  const filedFrom = sp.get("filed_from");
  const filedTo = sp.get("filed_to");
  return items.filter((i) => {
    const family = formFamily(i.form_type);
    if (forms.length && (!family || !forms.includes(family))) return false;
    if (directions.length && (!i.direction || !directions.includes(i.direction))) return false;
    if (codes.length && !i.codes.some((c) => codes.includes(c))) return false;
    if (roles.length && (!i.top_role || !roles.includes(i.top_role))) return false;
    if (sectors.length && (!i.sector || !sectors.includes(i.sector))) return false;
    if (badges.length && !i.badges.some((b) => badges.includes(b))) return false;
    if (minV !== null && (i.value_usd ?? -Infinity) < minV) return false;
    if (maxV !== null && (i.value_usd ?? Infinity) > maxV) return false;
    if (minM !== null && (i.market_cap_usd ?? -Infinity) < minM) return false;
    if (maxM !== null && (i.market_cap_usd ?? Infinity) > maxM) return false;
    if (maxLag !== null && (i.lag_days ?? Infinity) > maxLag) return false;
    if (issuerCik !== null && i.issuer?.cik !== issuerCik) return false;
    if (ownerCik !== null && !i.owners.some((o) => o.cik === ownerCik)) return false;
    if (!include && i.plan_10b5_1 !== "none" && i.plan_10b5_1 !== null) return false;
    if (filedFrom && i.filed_date < filedFrom) return false;
    if (filedTo && i.filed_date > filedTo) return false;
    return true;
  });
}

const [doeBuy, roeBuy, groupBuy, roeSell] = SEED_FEED;
const lateFiling = FEED.find((i) => i.badges.includes("late_filing"));

/** `/api/feed/summary`: the seed world's busiest week, reported for the requested date. */
export function feedSummary(date: string): Schema<"FeedSummary"> {
  return {
    date,
    counts_by_form: { "4": 4, "144": 1, "13F-HR": 1 },
    top_buys: [groupBuy, roeBuy, doeBuy],
    top_sells: [roeSell],
    clusters: [
      {
        issuer: ACME,
        start_date: "2024-06-04",
        end_date: "2024-06-05",
        owner_count: 3,
        total_value_usd: (groupBuy.value_usd ?? 0) + (roeBuy.value_usd ?? 0) + (doeBuy.value_usd ?? 0),
      },
    ],
    late_filings: lateFiling ? [lateFiling] : [],
  };
}

/**
 * The fictional entities behind every mock, mirroring the API test seed world
 * (plan 06, "Test seed world"): same names, CIKs, tickers, CUSIPs and periods.
 */
import type { Schema } from "@/api/client";

type IssuerRef = Schema<"IssuerRef">;
type OwnerRef = Schema<"OwnerRef">;

/** The last trading day in the seed world; every "latest" value is as of this date. */
export const AS_OF = "2024-06-07";

export const ACME: IssuerRef = { cik: 1000001, name: "Acme Corp", ticker: "ACME" };
export const GLOBEX: IssuerRef = { cik: 1000002, name: "Globex Inc", ticker: "GLBX" };
export const OLD_CO: IssuerRef = { cik: 1000003, name: "Old Co", ticker: "XYZA" };
export const NEW_CO: IssuerRef = { cik: 1000004, name: "New Co", ticker: "XYZ" };

export interface IssuerInfo {
  ref: IssuerRef;
  /** Former tickers, newest first. */
  former: string[];
  exchange: string;
  sector: string;
  sic: number;
  sicDescription: string;
  sharesOutstanding: number;
  lastClose: number;
  cusip: string;
  /** First date of bars in the mock price history. */
  barsFrom: string;
  seed: number;
}

export const ISSUERS: IssuerInfo[] = [
  {
    ref: ACME,
    former: [],
    exchange: "Nasdaq",
    sector: "Technology",
    sic: 7372,
    sicDescription: "Services-Prepackaged Software",
    sharesOutstanding: 250_000_000,
    lastClose: 10.0,
    cusip: "000000AA1",
    barsFrom: "2021-06-07",
    seed: 11,
  },
  {
    ref: GLOBEX,
    former: ["GBX"],
    exchange: "NYSE",
    sector: "Communication Services",
    sic: 4841,
    sicDescription: "Cable & Other Pay Television Services",
    sharesOutstanding: 200_000_000,
    lastClose: 42.5,
    cusip: "000000BB2",
    barsFrom: "2021-06-07",
    seed: 22,
  },
  {
    ref: OLD_CO,
    former: ["XYZ"],
    exchange: "NYSE",
    sector: "Industrials",
    sic: 3560,
    sicDescription: "General Industrial Machinery & Equipment",
    sharesOutstanding: 80_000_000,
    lastClose: 23.4,
    cusip: "000000CC3",
    barsFrom: "2021-06-07",
    seed: 33,
  },
  {
    ref: NEW_CO,
    former: [],
    exchange: "Nasdaq",
    sector: "Health Care",
    sic: 2834,
    sicDescription: "Pharmaceutical Preparations",
    sharesOutstanding: 60_000_000,
    lastClose: 15.3,
    cusip: "000000DD4",
    barsFrom: "2021-06-07",
    seed: 44,
  },
];

/** Latest close by current ticker; mock bars end exactly on these values. */
export const AS_OF_CLOSE = Object.fromEntries(ISSUERS.map((i) => [i.ref.ticker, i.lastClose])) as Record<
  "ACME" | "GLBX" | "XYZA" | "XYZ",
  number
>;

export function issuerInfo(cik: number): IssuerInfo | undefined {
  return ISSUERS.find((i) => i.ref.cik === cik);
}

export function marketCap(cik: number): number | null {
  const info = issuerInfo(cik);
  return info ? info.sharesOutstanding * info.lastClose : null;
}

export const DOE: OwnerRef = { cik: 2000001, name: "Doe Jane" };
export const ROE: OwnerRef = { cik: 2000002, name: "Roe Richard" };
export const ACME_HOLDINGS: OwnerRef = { cik: 2000003, name: "Acme Holdings LP" };
export const SMITH: OwnerRef = { cik: 2000004, name: "Smith John" };
export const NEW_PERSON: OwnerRef = { cik: 2000005, name: "New Person" };
export const OWNERS: OwnerRef[] = [DOE, ROE, ACME_HOLDINGS, SMITH, NEW_PERSON];

export const EXAMPLE_CAPITAL: OwnerRef = { cik: 3000001, name: "Example Capital Management" };
/** A 13F filer that isn't tracked, so it has holdings but no copycat performance. Name and
 * CIK match the backend seed world exactly (ws/e-api backend/tests/api/seed.py SMALL_FUND). */
export const QUIET_HARBOR: OwnerRef = { cik: 3999999, name: "Small Fry Advisors" };
export const FUNDS: OwnerRef[] = [EXAMPLE_CAPITAL, QUIET_HARBOR];

export function secUrl(cik: number, accession: string): string {
  return `https://www.sec.gov/Archives/edgar/data/${cik}/${accession.replace(/-/g, "")}/${accession}-index.htm`;
}

export const CODE_LABELS: Record<string, string> = {
  P: "Open-market buy",
  S: "Open-market sale",
  A: "Grant/award",
  M: "Option exercise",
  F: "Tax withholding",
  G: "Gift",
};

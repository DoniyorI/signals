/** Domain vocabularies shared by filters and mocks. Values mirror `signals.domain.types`. */

export const ROLES = [
  "CEO",
  "CFO",
  "COO",
  "President",
  "Chair",
  "General Counsel",
  "Other officer",
  "Director",
  "10% owner",
  "Other",
] as const;

export const SECTORS = [
  "Communication Services",
  "Consumer Discretionary",
  "Consumer Staples",
  "Energy",
  "Financials",
  "Health Care",
  "Industrials",
  "Materials",
  "Real Estate",
  "Technology",
  "Utilities",
] as const;

/** Form families accepted by `/api/feed?forms=`; each includes its amendments. */
export const FORM_FAMILIES = ["3", "4", "5", "144", "13F", "13D", "13G"] as const;

export const FUND_FORM_TYPES = ["13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"];

/** Which family a raw form type belongs to (for filtering and labels). */
export function formFamily(formType: string): (typeof FORM_FAMILIES)[number] | null {
  const base = formType.replace(/\/A$/, "");
  if (base === "3" || base === "4" || base === "5" || base === "144") return base;
  if (FUND_FORM_TYPES.includes(formType)) return "13F";
  if (base === "SCHEDULE 13D") return "13D";
  if (base === "SCHEDULE 13G") return "13G";
  return null;
}

export function isFundForm(formType: string): boolean {
  return FUND_FORM_TYPES.includes(formType);
}

export const WINDOWS = ["ytd", "1y", "3y", "5y"] as const;
export type WindowName = (typeof WINDOWS)[number];

export const HORIZONS = ["1m", "3m", "6m", "12m"] as const;
export type HorizonName = (typeof HORIZONS)[number];

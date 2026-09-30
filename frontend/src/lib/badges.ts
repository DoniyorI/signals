/** Badge and 10b5-1 labels. The rules behind each badge are spec section 9.8. */

export const BADGE_LABELS: Record<string, string> = {
  cluster_buy: "Cluster buy",
  late_filing: "Late filing",
  first_buy_2y: "First buy in 2y",
  dip_buy: "Dip buy",
  big_stake: "Big stake",
  form144_matched: "Pre-announced (144)",
  top_exec: "CEO/CFO/President",
};

export const BADGE_HELP: Record<string, string> = {
  cluster_buy:
    "Three or more different insiders (or insider groups) bought this stock on the open market, with first trades within 14 calendar days of each other.",
  late_filing:
    "Filed on or after the 3rd SEC business day after the trade. Section 16 requires filing within 2 business days.",
  first_buy_2y: "This insider's first open-market buy of this stock in the past 24 months.",
  dip_buy: "Bought after the stock fell 20% or more over the previous 60 trading days.",
  big_stake: "The buy grew the insider's stake by 20% or more, or was worth $1M or more.",
  form144_matched:
    "Announced in advance: the same person filed a Form 144 notice of proposed sale for this stock within the 90 days before selling.",
  top_exec: "The insider is the company's CEO, CFO or President.",
};

export const PLAN_LABELS: Record<"flag" | "footnote" | "none", string | null> = {
  flag: "10b5-1 plan",
  footnote: "10b5-1 (footnote)",
  none: null,
};

/** The display label for any badge key, including keys added after this build. */
export function badgeLabel(badge: string): string {
  return BADGE_LABELS[badge] ?? badge.replace(/_/g, " ");
}

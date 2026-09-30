import type { Basis } from "@/components/controls/BasisToggle";

/**
 * Reads the shared `basis` / `include_10b5_1` URL params the same way `BasisToggle` and
 * `TenB51Toggle` write them, so a page's own data fetch always agrees with what its toggles
 * show (plan 07, Global Constraints: basis defaults to filed, "Hide 10b5-1" defaults on).
 */
export function basisParam(sp: URLSearchParams): Basis {
  return sp.get("basis") === "executed" ? "executed" : "filed";
}

/** "Hide 10b5-1" defaults on, i.e. this is `false` unless the URL says otherwise. */
export function includeParam(sp: URLSearchParams): boolean {
  return sp.get("include_10b5_1") === "true";
}

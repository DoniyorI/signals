import { Switch } from "@/components/ui/switch";
import { useUrlState } from "@/hooks/useUrlState";

/**
 * Reads/writes `?include_10b5_1=`. "Hide 10b5-1" defaults on, i.e. `include_10b5_1=false`
 * (plan 07, Global Constraints) — 10b5-1 plan trades are pre-scheduled, not a fresh signal.
 */
export function TenB51Toggle() {
  const [include, setInclude] = useUrlState<boolean>(
    "include_10b5_1",
    false,
    (raw) => raw === "true",
    (v) => String(v),
  );
  return (
    <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
      <Switch
        checked={!include}
        onCheckedChange={(hide) => setInclude(!hide)}
        aria-label="Hide 10b5-1 plan trades"
      />
      Hide 10b5-1
    </label>
  );
}

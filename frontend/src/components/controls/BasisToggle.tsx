import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useUrlState } from "@/hooks/useUrlState";

export type Basis = "filed" | "executed";

function parseBasis(raw: string | null): Basis {
  return raw === "executed" ? "executed" : "filed";
}

/** Reads/writes `?basis=`. Defaults to "filed" (returns measured from the filing's SEC
 * acceptance time, not the trade date alone — spec ground rule 4). */
export function BasisToggle() {
  const [basis, setBasis] = useUrlState<Basis>("basis", "filed", parseBasis, (v) => v);
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      value={basis}
      onValueChange={(next) => next && setBasis(parseBasis(next))}
      aria-label="Return basis"
    >
      <ToggleGroupItem value="filed">From filing</ToggleGroupItem>
      <ToggleGroupItem value="executed">From trade</ToggleGroupItem>
    </ToggleGroup>
  );
}

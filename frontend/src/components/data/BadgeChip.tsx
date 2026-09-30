import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { BADGE_HELP, badgeLabel } from "@/lib/badges";

/** A badge pill (spec 9.8); hovering explains the rule that set it. */
export function BadgeChip({ badge }: { badge: string }) {
  const help = BADGE_HELP[badge];
  const chip = (
    <Badge variant="secondary" className="font-normal">
      {badgeLabel(badge)}
    </Badge>
  );
  if (!help) return chip;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{chip}</TooltipTrigger>
      <TooltipContent>{help}</TooltipContent>
    </Tooltip>
  );
}

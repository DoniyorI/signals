import { TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

/** A failed-query placeholder, with an optional retry action. */
export function ErrorState({
  title = "Something went wrong",
  description,
  action,
}: {
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-border bg-card py-12 text-center">
      <TriangleAlert className="size-5 text-neg" aria-hidden />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {description && <p className="max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

import { Button } from "@base-ui/react/button";
import type { ReactNode } from "react";

/** Chip（DESIGN.md 6.20）：高 40、全圓、1px leaf 框，點了就送出該選項（例如 5 號追問的選項）。 */
export function Chip({
  children,
  onClick,
  disabled,
  ...rest
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  "data-testid"?: string;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="min-h-10 rounded-full border border-leaf bg-white px-4 t-caption-bold text-brand hover:bg-leaf-soft focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf disabled:cursor-not-allowed disabled:opacity-40 data-[disabled]:cursor-not-allowed data-[disabled]:opacity-40"
      {...rest}
    >
      {children}
    </Button>
  );
}

/** 一排 Chip：可換行、間距 10。 */
export function ChipGroup({ children, ...rest }: { children: ReactNode; "data-testid"?: string }) {
  return (
    <div className="flex flex-wrap gap-2.5" {...rest}>
      {children}
    </div>
  );
}

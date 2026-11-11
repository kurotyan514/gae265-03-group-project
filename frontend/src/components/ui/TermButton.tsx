import { Button } from "@base-ui/react/button";
import type { ReactNode } from "react";
import { InfoIcon } from "../icons";

/** 名詞按鈕（DESIGN.md 6.13）：文字後面加 ⓘ，點了開名詞解釋。 */
export function TermButton({
  children,
  onClick,
  className = "t-label text-ink",
}: {
  children: ReactNode;
  onClick: () => void;
  /** 字級與顏色；預設是 label。 */
  className?: string;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1 text-left hover:underline hover:underline-offset-[3px] focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf ${className}`}
    >
      <span>{children}</span>
      <InfoIcon className="size-4 flex-none text-leaf-text" />
    </Button>
  );
}

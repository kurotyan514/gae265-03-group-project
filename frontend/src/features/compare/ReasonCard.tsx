import { Button } from "@base-ui/react/button";
import { useState } from "react";
import { ChevronIcon } from "../../components/icons";
import { lnk } from "../../components/ui/buttons";

/**
 * 推薦理由卡（DESIGN.md 6.12）：標題、理由、「看推薦依據」展開（箭頭旋轉 200ms）。
 * 理由與依據的文字由後端程式組好，這裡只負責畫。
 */
export function ReasonCard({ reason, basis }: { reason: string; basis: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-line/60 bg-white p-5 shadow-card md:rounded-panel md:px-8 md:py-6">
      <h2 className="m-0 t-subsection-title text-heading">推薦理由與依據</h2>
      <p data-testid="reason" className="m-0 t-body text-ink">
        {reason}
      </p>
      <Button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={`${lnk} w-full justify-between border-t border-line pt-3`}
      >
        {open ? "收合推薦依據" : "看推薦依據"}
        <ChevronIcon
          className={`size-4 transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-90" : ""}`}
        />
      </Button>
      {open && (
        <ol data-testid="basis" className="m-0 list-decimal space-y-1 pl-5 t-body text-ink">
          {basis.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      )}
    </section>
  );
}

import { Tabs as BaseTabs } from "@base-ui/react/tabs";
import type { ReactNode } from "react";

/**
 * 分頁（DESIGN.md 6.16）：底線樣式；手機可橫向捲動。`starred`＝涵蓋使用者在意的點，標 ★。
 * 用法：`<Tabs.Root><TabList><Tab value="…">…</Tab></TabList><Tabs.Panel value="…">…</Tabs.Panel></Tabs.Root>`
 */
export function TabList({ children }: { children: ReactNode }) {
  return (
    <BaseTabs.List className="flex gap-1 overflow-x-auto border-b-2 border-brand pt-1 [scrollbar-width:thin]">
      {children}
    </BaseTabs.List>
  );
}

export function Tab({
  value,
  starred = false,
  children,
}: {
  value: string;
  starred?: boolean;
  children: ReactNode;
}) {
  return (
    <BaseTabs.Tab
      value={value}
      className="-mb-0.5 shrink-0 whitespace-nowrap rounded-t-tag border border-b-0 border-transparent bg-transparent px-4 py-2.5 t-caption-bold text-muted hover:text-brand focus-visible:outline-3 focus-visible:outline-offset-[-3px] focus-visible:outline-leaf data-[active]:border-brand data-[active]:bg-white data-[active]:text-brand"
    >
      {children}
      {starred && <span className="text-sun"> ★</span>}
    </BaseTabs.Tab>
  );
}

export const Tabs = BaseTabs;

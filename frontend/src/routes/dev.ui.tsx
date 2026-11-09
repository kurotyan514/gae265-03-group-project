import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import type { Concern, PlanCardOut } from "../client/types.gen";
import { ActionBar } from "../components/ui/ActionBar";
import { btn, btnPri, btnSm, btnSmPri, lnk, wide } from "../components/ui/buttons";
import { AskBar, ChatDivider, ChatLog, ChatMessage } from "../components/ui/Chat";
import { Chip, ChipGroup } from "../components/ui/Chip";
import { Dialog, DialogShell, PickRow } from "../components/ui/DialogShell";
import {
  Field,
  FieldError,
  FieldHint,
  FieldOk,
  FieldWarn,
  fieldInput,
} from "../components/ui/Field";
import { FileDrop, FilePickButton, PickedFile } from "../components/ui/FileDrop";
import { LoadingOverlay } from "../components/ui/LoadingOverlay";
import { PageHead } from "../components/ui/PageHead";
import { PlaceholderButton } from "../components/ui/PlaceholderButton";
import { Tab, TabList, Tabs } from "../components/ui/Tabs";
import { ConclusionPill, FactPill, Pill, ProgressPill, TodoTag } from "../components/ui/Tag";
import { TermButton } from "../components/ui/TermButton";
import { ToastProvider, useToast } from "../components/ui/Toast";
import { ComparisonTable } from "../features/compare/ComparisonTable";
import { ConcernCard } from "../features/compare/ConcernCard";
import { DaysSummary } from "../features/compare/DaysSummary";
import { PlanCard } from "../features/compare/PlanCard";
import { ReasonCard } from "../features/compare/ReasonCard";
import { MiniTable, SimulationCard, Story } from "../features/compare/ScenarioParts";

export const Route = createFileRoute("/dev/ui")({
  component: UiPreview,
});

const CONCERN_SAMPLES: Concern[] = [
  "突然生病就醫",
  "需要緊急送醫或家屬趕來",
  "行程取消或更改",
  "班機延誤",
  "行李延誤",
  "行李遺失或損壞",
  "證件遺失",
  "信用卡盜刷",
  "不小心弄傷別人或弄壞東西",
];

const SAMPLE_PLAN: PlanCardOut = {
  plan_code: "SAMPLE",
  name: "示意方案-進階型",
  company: "示意保險公司",
  url: "https://example.com",
  sum_insured: 3_000_000,
  recommended_sum_insured: 3_000_000,
  sum_insured_options: [3_000_000, 5_000_000],
  premium: 985,
} as PlanCardOut;

const panel = "space-y-3 rounded-2xl border border-line/60 bg-white p-5 shadow-card";

/** 功能二共用元件的預覽（#215）：設計稿 DESIGN.md 第 6 節的元件，方便對照與 e2e 驗證。 */
function UiPreview() {
  return (
    <ToastProvider>
      <Preview />
    </ToastProvider>
  );
}

function Preview() {
  const toast = useToast();
  const [ask, setAsk] = useState("");
  const [file, setFile] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"center" | "bottom" | null>(null);
  const [picked, setPicked] = useState<Concern[]>(["班機延誤", "突然生病就醫", "證件遺失"]);
  const [sum, setSum] = useState(5_000_000);
  const [loading, setLoading] = useState(false);

  return (
    <div className="space-y-6 bg-paper p-4 font-ui" data-testid="ui-preview">
      <PageHead
        crumb="出事了：幫我處理理賠 · 元件預覽"
        title="日本 2026/07/05～07/10"
        meta="富邦產險 B 方案 · 400 萬"
        note="示意資料"
      />

      <section className={panel} aria-label="按鈕">
        <h2 className="t-section-title text-heading">按鈕</h2>
        <ActionBar>
          <button type="button" className={btn}>
            預設
          </button>
          <button type="button" className={btnPri}>
            主要
          </button>
          <button type="button" className={btnSm}>
            小
          </button>
          <button type="button" className={btnSmPri}>
            小・主要
          </button>
          <button type="button" className={btn} disabled>
            停用
          </button>
          <a href="/dev/ui" className={lnk}>
            文字連結
          </a>
          <ActionBar.Push>
            <button type="button" className={`${btnPri} ${wide}`}>
              滿寬主要
            </button>
          </ActionBar.Push>
        </ActionBar>
        <h3 className="t-label text-heading">反灰按鈕（點了跳 Toast「暫無作用」）</h3>
        <div className="flex flex-wrap items-center gap-3">
          <PlaceholderButton data-testid="placeholder-small" kind="small">
            有新狀況
          </PlaceholderButton>
          <PlaceholderButton data-testid="placeholder-button">下載全部文件</PlaceholderButton>
          <PlaceholderButton data-testid="placeholder-link" kind="link">
            看提醒信範本
          </PlaceholderButton>
          <PlaceholderButton data-testid="placeholder-danger" kind="danger-link">
            刪除
          </PlaceholderButton>
          <button type="button" className={btnSm} onClick={() => toast.show("已存檔")}>
            顯示 Toast
          </button>
        </div>
      </section>

      <section className={panel} aria-label="標籤">
        <h2 className="t-section-title text-heading">標籤</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Pill>預設</Pill>
          <Pill tone="need">還缺 8 份文件</Pill>
          <Pill tone="sent">文件已備齊</Pill>
          <Pill tone="closed">已結案</Pill>
          <ProgressPill>待辦 3／11</ProgressPill>
          <ConclusionPill conclusion="applicable">可能適用</ConclusionPill>
          <ConclusionPill conclusion="excluded">依條款不在保障範圍</ConclusionPill>
          <ConclusionPill conclusion="insufficient">資訊不足</ConclusionPill>
          <FactPill>發生日期：2026/07/09</FactPill>
        </div>
        <p className="t-label-lg text-ink">
          請航空公司開立班機延誤／取消證明
          <TodoTag tone="new">新增</TodoTag>
          <TodoTag tone="missing">未附文件</TodoTag>
          <TodoTag>不適用</TodoTag>
        </p>
      </section>

      <section className={panel} aria-label="表單">
        <h2 className="t-section-title text-heading">表單</h2>
        <Field label="目的地" htmlFor="ui-dest">
          <select id="ui-dest" className={`${fieldInput} w-full`}>
            <option>請選擇</option>
            <option>日本</option>
          </select>
          <FieldHint>旅遊天數最多 10 天（含頭尾）</FieldHint>
          <FieldOk data-testid="ui-ok">由保單自動帶入，可修改</FieldOk>
          <FieldWarn data-testid="ui-warn">保單上讀不到，請自行選擇</FieldWarn>
          <FieldError data-testid="ui-error">出發日要從今天起。</FieldError>
        </Field>
        <FileDrop title="上傳保單" description="PDF，10 MB 內。個資會先移除再讀取，原檔不保存。">
          <FilePickButton
            label="選擇保單檔案"
            onFiles={(f) => setFile(f[0]?.name ?? "")}
            inputTestId="ui-file"
          />
          {file && <PickedFile name={file} />}
        </FileDrop>
      </section>

      <section className={panel} aria-label="對話">
        <h2 className="t-section-title text-heading">對話</h2>
        <ChatLog data-testid="ui-chat">
          <ChatMessage from="ai">發生什麼事了？用一兩句話描述就好。</ChatMessage>
          <ChatMessage from="me">11/03 在曼谷逛夜市，護照被偷了</ChatMessage>
          <ChatDivider>以下依新的推薦回答</ChatDivider>
          <ChatMessage from="ai">
            <ConclusionPill conclusion="applicable">可能適用</ConclusionPill>
            <span>住宿費屬旅程縮短，額度內依收據理賠。</span>
            <span className="t-caption text-muted">依據：旅程縮短費用保險（TA45）</span>
          </ChatMessage>
        </ChatLog>
        <ChipGroup>
          <Chip>是</Chip>
          <Chip>否</Chip>
          <Chip>不知道</Chip>
        </ChipGroup>
        <AskBar
          value={ask}
          onChange={setAsk}
          onSubmit={() => setAsk("")}
          maxLength={500}
          placeholder="回答上面的問題，或點選項"
          inputTestId="ui-ask"
          submitTestId="ui-ask-submit"
        />
      </section>

      <section className={panel} aria-label="功能一元件">
        <h2 className="t-section-title text-heading">功能一：在意事項、天數、方案、理由</h2>
        <div data-testid="ui-concerns" className="grid grid-cols-2 gap-3 md:grid-cols-3">
          {CONCERN_SAMPLES.map((c) => (
            <ConcernCard
              key={c}
              concern={c}
              order={picked.indexOf(c) + 1}
              disabled={!picked.includes(c) && picked.length >= 3}
              onClick={() =>
                setPicked(picked.includes(c) ? picked.filter((x) => x !== c) : [...picked, c])
              }
            />
          ))}
        </div>
        <DaysSummary>共 6 天</DaysSummary>
        <div className="grid gap-4 md:grid-cols-2">
          <PlanCard
            label="推薦"
            highlight
            plan={SAMPLE_PLAN}
            days={6}
            disabled={false}
            onChange={() => {}}
          />
          <PlanCard
            label="次推薦"
            highlight={false}
            plan={{ ...SAMPLE_PLAN, name: "示意方案-基礎型", sum_insured: sum }}
            days={6}
            disabled={false}
            onChange={setSum}
          />
        </div>
        <ReasonCard
          reason="你最在意「班機延誤」，推薦方案在這一項是 9,000 元。"
          basis={["依據一", "依據二"]}
        />
        <TermButton onClick={() => toast.show("名詞解釋")}>班機延誤</TermButton>
      </section>

      <section className={panel} aria-label="功能一表格與分頁">
        <h2 className="t-section-title text-heading">功能一：比較表、分頁、試算卡</h2>
        <ComparisonTable
          columns={[
            { label: "推薦", head: "推薦｜示意方案-進階型" },
            { label: "次推薦", head: "次推薦｜示意方案-基礎型" },
          ]}
          rows={[
            {
              key: "delay",
              label: "班機延誤",
              concernOrder: 1,
              onTerm: () => toast.show("班機延誤"),
              cells: ["班機延誤：9,000 元", "未列"],
            },
            {
              key: "death",
              label: "身故",
              onTerm: () => toast.show("身故"),
              cells: ["身故：3,000,000 元", "身故：3,000,000 元"],
            },
          ]}
        />
        <Tabs.Root defaultValue="a">
          <TabList>
            <Tab value="a" starred>
              班機延誤
            </Tab>
            <Tab value="b">行李遺失</Tab>
            <Tab value="c">海外就醫</Tab>
          </TabList>
          <Tabs.Panel value="a" className="flex flex-col gap-4 pt-4">
            <Story>你搭 08:00 的班機，因故延誤 8 小時。</Story>
            <SimulationCard conclusion="推薦方案賠 9,000 元，次推薦賠 6,000 元。">
              <MiniTable
                headLabel="保障項目"
                columns={[
                  { key: "r", label: "推薦" },
                  { key: "a", label: "次推薦" },
                ]}
                rows={[
                  {
                    key: "x",
                    head: <TermButton onClick={() => {}}>班機延誤</TermButton>,
                    cells: [<b key="r">賠 9,000 元</b>, <b key="a">賠 6,000 元</b>],
                  },
                ]}
              />
            </SimulationCard>
          </Tabs.Panel>
          <Tabs.Panel value="b" className="pt-4">
            行李遺失
          </Tabs.Panel>
          <Tabs.Panel value="c" className="pt-4">
            海外就醫
          </Tabs.Panel>
        </Tabs.Root>
        <button
          type="button"
          className={btn}
          data-testid="open-loading"
          onClick={() => {
            setLoading(true);
            setTimeout(() => setLoading(false), 1500);
          }}
        >
          顯示載入遮罩
        </button>
      </section>
      {loading && <LoadingOverlay>正在比較方案…</LoadingOverlay>}

      <section className={panel} aria-label="對話框">
        <h2 className="t-section-title text-heading">對話框</h2>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            className={btn}
            onClick={() => setDialog("center")}
            data-testid="open-center"
          >
            置中對話框
          </button>
          <button
            type="button"
            className={btn}
            onClick={() => setDialog("bottom")}
            data-testid="open-bottom"
          >
            底部抽屜
          </button>
        </div>
      </section>

      <DialogShell
        open={dialog === "center"}
        onOpenChange={(o) => !o && setDialog(null)}
        title="確定寄出？"
        description={<p>選擇後此行程即結案，之後無法再新增狀況或修改。</p>}
        testId="ui-dialog-center"
        actions={
          <>
            <Dialog.Close className={btn}>取消</Dialog.Close>
            <Dialog.Close className={btnPri}>確定寄出</Dialog.Close>
          </>
        }
      />
      <DialogShell
        open={dialog === "bottom"}
        onOpenChange={(o) => !o && setDialog(null)}
        title="從過去的比較帶入"
        variant="bottom"
        testId="ui-dialog-bottom"
        actions={<Dialog.Close className={btn}>取消</Dialog.Close>}
      >
        <PickRow onClick={() => setDialog(null)}>日本 · 2026/07/05～07/10</PickRow>
        <PickRow onClick={() => setDialog(null)}>泰國 · 2026/11/02～11/06</PickRow>
      </DialogShell>
    </div>
  );
}

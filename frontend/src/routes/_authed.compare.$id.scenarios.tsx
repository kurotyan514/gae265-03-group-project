import { Button } from "@base-ui/react/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { Fragment, useState } from "react";
import {
  askComparisonQuestionMutation,
  getComparisonScenariosOptions,
} from "../client/@tanstack/react-query.gen";
import type {
  QuestionAnswerOut,
  ScenarioOut,
  ScenarioPlanOut,
  ScenarioRowOut,
} from "../client/types.gen";
import { ActionBar } from "../components/ui/ActionBar";
import { btn, lnk } from "../components/ui/buttons";
import { AskBar, ChatLog, ChatMessage } from "../components/ui/Chat";
import { Chip, ChipGroup } from "../components/ui/Chip";
import { FieldError } from "../components/ui/Field";
import { PageHead } from "../components/ui/PageHead";
import { Tab, TabList, Tabs } from "../components/ui/Tabs";
import { TermButton } from "../components/ui/TermButton";
import { MiniTable, SimulationCard, Story } from "../features/compare/ScenarioParts";
import { type Term, TermDialog } from "../features/compare/TermDialog";
import { WithComparison } from "../features/compare/WithComparison";
import { card } from "../features/incident/shared";
import { money } from "../lib/format";

export const Route = createFileRoute("/_authed/compare/$id/scenarios")({
  component: ScenariosPage,
});

const planLabel = (recommended: boolean) => (recommended ? "推薦" : "次推薦");

const MAX_LENGTH = 300; // 同後端 MAX_QUESTION_LENGTH
const MAX_HISTORY = 3; // 同後端 MAX_HISTORY_TURNS
const FAQ = [
  "兩個方案差在哪？",
  "班機延誤多久才能賠？",
  "行李遺失怎麼賠？",
  "在國外看病要先自己付錢嗎？",
];

/** 1-4 情境試算與問答：試算卡片全由後端程式算出，問答只存在這個元件，離開就清空。 */
function ScenariosPage() {
  const { id } = Route.useParams();
  return (
    <WithComparison id={id}>
      {(c) =>
        c.recommendation ? (
          <main className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
            <PageHead
              crumb="出發前：幫我選方案"
              title="情境試算與問答"
              meta="選一個情境看看各方案賠多少，也可以直接問問題。"
            />
            <Scenarios id={id} />
            <Chat id={id} />
            <ActionBar twoColumns>
              <Link to="/compare/$id/result" params={{ id }} className={btn}>
                回比較表
              </Link>
              <ActionBar.Push>
                <Link to="/" className={btn}>
                  完成
                </Link>
              </ActionBar.Push>
            </ActionBar>
          </main>
        ) : (
          // 還沒有推薦：回 1-2
          <Navigate to="/compare/$id/concerns" params={{ id }} replace />
        )
      }
    </WithComparison>
  );
}

function Scenarios({ id }: { id: string }) {
  const scenarios = useQuery(getComparisonScenariosOptions({ path: { comparison_id: id } }));

  if (scenarios.error) return <FieldError>情境試算讀取失敗，請重新整理。</FieldError>;
  if (!scenarios.data) return <p className="m-0 t-body text-muted">讀取中…</p>;
  return (
    <Tabs.Root defaultValue={scenarios.data[0]?.tab}>
      <TabList>
        {scenarios.data.map((s) => (
          <Tab key={s.tab} value={s.tab} starred={s.starred}>
            {s.tab}
          </Tab>
        ))}
      </TabList>
      {scenarios.data.map((s) => (
        <Tabs.Panel key={s.tab} value={s.tab} className="flex flex-col gap-4 pt-5">
          <Story>{s.story}</Story>
          <p className="m-0 t-caption text-muted">試算假設：{s.assumption}</p>
          <ScenarioCard scenario={s} />
        </Tabs.Panel>
      ))}
    </Tabs.Root>
  );
}

/** 一格：第一行粗體是故事下的結果（有試算金額寫「賠 X 元」，否則照原文；不在保障範圍寫 result），第二行小字是保障項目。 */
function Cell({ p }: { p: ScenarioPlanOut }) {
  const headline = p.payout !== null ? `賠 ${money(p.payout)}` : (p.outcome ?? p.result);
  return (
    <div className="flex flex-col gap-0.5">
      <p className="m-0 t-label text-heading">{headline}</p>
      {p.benefit && <p className="m-0 t-caption text-muted">{p.benefit}</p>}
    </div>
  );
}

/** 短名稱的說明框補充：兩個方案各自採用的保障項目與條款依據（沒有依據就不顯示）。 */
function rowTerm(r: ScenarioRowOut): Term {
  return {
    title: r.name,
    explanation: r.name_explanation,
    details: r.plans.map((p) => (
      <div key={p.plan_code} className="flex flex-col gap-1">
        <p className="m-0 t-label text-heading">
          {planLabel(p.recommended)}｜{p.company} {p.name}
        </p>
        <p className="m-0">{p.benefit ?? p.result}</p>
        {p.basis && <p className="m-0 t-caption text-muted">條款依據：{p.basis}</p>}
      </div>
    )),
  };
}

function ScenarioCard({ scenario }: { scenario: ScenarioOut }) {
  const [term, setTerm] = useState<Term | null>(null);
  const plans = scenario.rows[0]?.plans ?? [];
  return (
    <SimulationCard conclusion={scenario.conclusion}>
      <MiniTable
        headLabel="保障項目"
        columns={plans.map((p) => ({
          key: p.plan_code,
          label: (
            <>
              <span className="block t-micro text-leaf-text">{planLabel(p.recommended)}</span>
              {p.company} {p.name}
            </>
          ),
        }))}
        rows={scenario.rows.map((r) => ({
          key: r.name,
          head: (
            <div className="flex flex-col items-start gap-0.5">
              <TermButton onClick={() => setTerm(rowTerm(r))}>{r.name}</TermButton>
              <TermButton
                className="t-caption text-muted"
                onClick={() => setTerm({ title: r.method, explanation: r.method_explanation })}
              >
                {r.method}
              </TermButton>
            </div>
          ),
          cells: r.plans.map((p) => <Cell key={p.plan_code} p={p} />),
        }))}
      />
      {scenario.note && (
        <p className="m-0 t-caption text-ink" data-testid="note">
          附註：{scenario.note}
        </p>
      )}
      <p className="m-0 t-caption text-muted">僅為依情境假設的試算，實際以保險公司審核為準。</p>
      <TermDialog term={term} onClose={() => setTerm(null)} />
    </SimulationCard>
  );
}

type Turn = { question: string; reply: QuestionAnswerOut };

function Chat({ id }: { id: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [showFaq, setShowFaq] = useState(true);
  const ask = useMutation(askComparisonQuestionMutation());

  const submit = (question: string) => {
    setShowFaq(false);
    ask.mutate(
      {
        path: { comparison_id: id },
        body: {
          question,
          history: turns
            .slice(-MAX_HISTORY)
            .map((t) => ({ question: t.question, answer: t.reply.answer })),
        },
      },
      { onSuccess: (reply) => setTurns((ts) => [...ts, { question, reply }]) },
    );
  };
  const empty = turns.length === 0 && !ask.isPending;
  const faq = (
    <ChipGroup>
      {FAQ.map((q) => (
        <Chip key={q} disabled={ask.isPending} onClick={() => submit(q)}>
          {q}
        </Chip>
      ))}
    </ChipGroup>
  );

  return (
    <section aria-label="問答" className={`${card} flex flex-col gap-4`}>
      <h2 className="m-0 t-section-title text-heading">問答</h2>
      {empty ? (
        <div className="flex flex-col gap-3 rounded-tile border border-line bg-paper p-4 md:p-5">
          <p className="m-0 t-body text-muted">
            點下方常見問題，或自己輸入。問答內容不會保存，離開這頁就會清空。
          </p>
          {showFaq && faq}
        </div>
      ) : (
        <ChatLog>
          {turns.map((t, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: 清單只會在尾端新增
            <Fragment key={i}>
              <ChatMessage from="me" data-testid="question">
                {t.question}
              </ChatMessage>
              <Answer reply={t.reply} />
            </Fragment>
          ))}
          {ask.isPending && ask.variables && (
            <>
              <ChatMessage from="me" data-testid="question">
                {ask.variables.body.question}
              </ChatMessage>
              <ChatMessage from="ai">
                <span role="status" className="t-body text-muted">
                  查詢條款中…
                </span>
              </ChatMessage>
            </>
          )}
        </ChatLog>
      )}
      {ask.error && <FieldError>回答失敗，請再試一次。</FieldError>}
      {!empty && showFaq && faq}
      {!empty && (
        <Button
          type="button"
          aria-expanded={showFaq}
          onClick={() => setShowFaq(!showFaq)}
          className={`${lnk} w-fit`}
        >
          常見問題
        </Button>
      )}
      <AskBar
        value={draft}
        onChange={setDraft}
        onSubmit={() => {
          submit(draft.trim());
          setDraft("");
        }}
        maxLength={MAX_LENGTH}
        placeholder="問問推薦方案的任何問題"
        disabled={ask.isPending}
        inputLabel="問題"
      />
      <p className="m-0 t-caption text-muted">回答由 AI 依條款整理，實際以保險公司審核為準。</p>
    </section>
  );
}

function Answer({ reply }: { reply: QuestionAnswerOut }) {
  const groups = reply.citations.filter((g) => g.citations.length > 0);
  return (
    <ChatMessage from="ai" data-testid="answer">
      {reply.original_only && (
        <p className="m-0 w-fit rounded-tag bg-warn-soft px-2 py-0.5 t-caption-bold text-warn-ink">
          無法產生白話說明，以下直接列出條款原文
        </p>
      )}
      <p className="m-0 whitespace-pre-wrap t-body text-ink">{reply.answer}</p>
      {groups.map((g) => (
        <div key={g.plan_code} className="flex flex-col gap-1 t-caption">
          <p className="m-0 t-caption-bold text-heading">
            依據｜{planLabel(g.recommended)}：{g.plan_name}
          </p>
          {g.citations.map((c) => (
            <details key={c.rule_id} className="rounded-tag border border-line bg-paper px-3 py-2">
              <summary className="cursor-pointer">
                {c.insurance_name} 第 {c.article_no} 條「{c.title}」（第 {c.page_start} 頁）
              </summary>
              <p className="mt-1 mb-0 whitespace-pre-wrap text-muted">{c.excerpt}</p>
            </details>
          ))}
        </div>
      ))}
    </ChatMessage>
  );
}

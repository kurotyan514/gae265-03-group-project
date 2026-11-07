import { Button } from "@base-ui/react/button";
import { Tabs } from "@base-ui/react/tabs";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, Navigate } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
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
import { type Term, TermDialog } from "../features/compare/TermDialog";
import { WithComparison } from "../features/compare/WithComparison";

export const Route = createFileRoute("/_authed/compare/$id/scenarios")({
  component: ScenariosPage,
});

const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50";
const linkClass = "text-blue-700 underline";
const money = (n: number) => `${n.toLocaleString("zh-TW")} 元`;
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
          <main className="space-y-6">
            <header>
              <h1 className="text-2xl font-bold">情境試算</h1>
              <p className="text-gray-600">選一個情境看看各方案賠多少，也可以直接問問題</p>
            </header>
            <Scenarios id={id} />
            <Chat id={id} />
            <div className="flex gap-2">
              <Link to="/compare/$id/result" params={{ id }} className={buttonClass}>
                回比較表
              </Link>
              <Link to="/" className={buttonClass}>
                完成
              </Link>
            </div>
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

  if (scenarios.error)
    return (
      <p role="alert" className="text-red-600">
        情境試算讀取失敗，請重新整理。
      </p>
    );
  if (!scenarios.data) return <p>讀取中…</p>;
  return (
    <Tabs.Root defaultValue={scenarios.data[0]?.tab}>
      <Tabs.List className="flex flex-wrap gap-2 border-b pb-2">
        {scenarios.data.map((s) => (
          <Tabs.Tab
            key={s.tab}
            value={s.tab}
            className="rounded-full border px-3 py-1 data-[selected]:border-blue-600 data-[selected]:bg-blue-600 data-[selected]:text-white"
          >
            {s.tab}
            {s.starred && " ★"}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {scenarios.data.map((s) => (
        <Tabs.Panel key={s.tab} value={s.tab} className="space-y-3 pt-4">
          <p>{s.story}</p>
          <p className="text-sm text-gray-600">試算假設：{s.assumption}</p>
          <ScenarioCard scenario={s} />
        </Tabs.Panel>
      ))}
    </Tabs.Root>
  );
}

const dash = <span className="text-gray-500">—</span>;

/** 一列在某個方案下的試算結果。 */
function Cell({ p }: { p: ScenarioPlanOut }) {
  return (
    <div className="space-y-1">
      <p>{p.result}</p>
      {p.benefit && <p className="text-gray-600">相關保障：{p.benefit}</p>}
      <p>最高賠多少：{p.max_amount === null ? dash : money(p.max_amount)}</p>
      <p>以這個故事來說：{p.outcome ?? dash}</p>
    </div>
  );
}

/** 短名稱的說明框補充：兩個方案各自採用的保障項目與條款依據（沒有依據就不顯示）。 */
function rowTerm(r: ScenarioRowOut): Term {
  return {
    title: r.name,
    explanation: r.name_explanation,
    details: r.plans.map((p) => (
      <div key={p.plan_code} className="text-sm">
        <p className="font-bold">
          {planLabel(p.recommended)}｜{p.company} {p.name}
        </p>
        <p>{p.benefit ?? p.result}</p>
        {p.basis && <p className="text-gray-600">條款依據：{p.basis}</p>}
      </div>
    )),
  };
}

function ScenarioCard({ scenario }: { scenario: ScenarioOut }) {
  const [term, setTerm] = useState<Term | null>(null);
  const plans = scenario.rows[0]?.plans ?? [];
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-700">
        模板試算・不經 AI
      </span>
      <p className="font-bold" data-testid="conclusion">
        {scenario.conclusion}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b text-left">
              <th className="p-2" />
              {plans.map((p) => (
                <th key={p.plan_code} className="p-2">
                  {p.company} {p.name}
                  {p.recommended && (
                    <span className="ml-1 rounded bg-blue-600 px-1 text-xs text-white">推薦</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {scenario.rows.map((r) => (
              <tr key={r.name} className="border-b align-top">
                <th scope="row" className="p-2 text-left font-normal whitespace-nowrap">
                  <Button
                    className={`${linkClass} font-medium`}
                    onClick={() => setTerm(rowTerm(r))}
                  >
                    {r.name}
                  </Button>
                  <Button
                    className={`${linkClass} ml-1 text-gray-600`}
                    onClick={() => setTerm({ title: r.method, explanation: r.method_explanation })}
                  >
                    {r.method}
                  </Button>
                </th>
                {r.plans.map((p) => (
                  <td key={p.plan_code} className="p-2">
                    <Cell p={p} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {scenario.note && (
        <p className="text-sm" data-testid="note">
          附註：{scenario.note}
        </p>
      )}
      <p className="text-sm text-gray-600">僅為依情境假設的試算，實際以保險公司審核為準。</p>
      <TermDialog term={term} onClose={() => setTerm(null)} />
    </section>
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
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(draft.trim());
    setDraft("");
  };
  const empty = turns.length === 0 && !ask.isPending;

  return (
    <section aria-label="問答" className="space-y-3 rounded-lg border p-4">
      {empty ? (
        <p className="text-gray-600">
          點下方常見問題，或自己輸入。問答內容不會保存，離開這頁就會清空。
        </p>
      ) : (
        <ol className="space-y-3">
          {turns.map((t, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: 清單只會在尾端新增
            <li key={i} className="space-y-2">
              <Question text={t.question} />
              <Answer reply={t.reply} />
            </li>
          ))}
          {ask.isPending && ask.variables && (
            <li className="space-y-2">
              <Question text={ask.variables.body.question} />
              <p role="status" className="text-gray-600">
                查詢條款中…
              </p>
            </li>
          )}
        </ol>
      )}
      {ask.error && (
        <p role="alert" className="text-red-600">
          回答失敗，請再試一次。
        </p>
      )}
      {showFaq && (
        <div className="flex flex-wrap gap-2">
          {FAQ.map((q) => (
            <Button
              key={q}
              disabled={ask.isPending}
              onClick={() => submit(q)}
              className="rounded-full border px-3 py-1 text-sm hover:bg-gray-100 data-[disabled]:opacity-50"
            >
              {q}
            </Button>
          ))}
        </div>
      )}
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          aria-label="問題"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={MAX_LENGTH}
          placeholder="問問推薦方案的任何問題"
          className="min-w-0 flex-1 rounded-md border px-2 py-1"
        />
        <Button type="submit" disabled={ask.isPending || !draft.trim()} className={buttonClass}>
          送出
        </Button>
        {!empty && (
          <Button
            aria-expanded={showFaq}
            onClick={() => setShowFaq(!showFaq)}
            className={linkClass}
          >
            常見問題
          </Button>
        )}
      </form>
      <p className="text-sm text-gray-600">回答由 AI 依條款整理，實際以保險公司審核為準。</p>
    </section>
  );
}

function Question({ text }: { text: string }) {
  return (
    <p
      className="ml-auto w-fit max-w-[80%] rounded-lg bg-blue-100 px-3 py-2"
      data-testid="question"
    >
      {text}
    </p>
  );
}

function Answer({ reply }: { reply: QuestionAnswerOut }) {
  const groups = reply.citations.filter((g) => g.citations.length > 0);
  return (
    <div
      className="max-w-[90%] space-y-2 rounded-lg border bg-gray-50 px-3 py-2"
      data-testid="answer"
    >
      {reply.original_only && (
        <p className="inline-block rounded bg-amber-100 px-2 py-0.5 text-sm text-amber-900">
          無法產生白話說明，以下直接列出條款原文
        </p>
      )}
      <p className="whitespace-pre-wrap">{reply.answer}</p>
      {groups.map((g) => (
        <div key={g.plan_code} className="space-y-1 text-sm">
          <p className="font-medium">
            依據｜{planLabel(g.recommended)}：{g.plan_name}
          </p>
          {g.citations.map((c) => (
            <details key={c.rule_id} className="rounded border bg-white px-2 py-1">
              <summary className="cursor-pointer">
                {c.insurance_name} 第 {c.article_no} 條「{c.title}」（第 {c.page_start} 頁）
              </summary>
              <p className="mt-1 whitespace-pre-wrap text-gray-700">{c.excerpt}</p>
            </details>
          ))}
        </div>
      ))}
    </div>
  );
}

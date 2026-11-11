import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { updateComparisonMutation } from "../client/@tanstack/react-query.gen";
import type { ComparisonOut, Concern } from "../client/types.gen";
import { ActionBar } from "../components/ui/ActionBar";
import { btn, btnPri } from "../components/ui/buttons";
import { Field, FieldError, FieldHint, fieldInput } from "../components/ui/Field";
import { LoadingOverlay } from "../components/ui/LoadingOverlay";
import { PageHead } from "../components/ui/PageHead";
import { ConcernCard } from "../features/compare/ConcernCard";
import { WithComparison } from "../features/compare/WithComparison";
import { card } from "../features/incident/shared";

export const Route = createFileRoute("/_authed/compare/$id/concerns")({
  component: ConcernsPage,
});

// 畫面順序；satisfies 讓產生的 Concern 型別多或少一個時編譯失敗
const CONCERNS = Object.keys({
  突然生病就醫: 0,
  需要緊急送醫或家屬趕來: 0,
  行程取消或更改: 0,
  班機延誤: 0,
  行李延誤: 0,
  行李遺失或損壞: 0,
  證件遺失: 0,
  信用卡盜刷: 0,
  不小心弄傷別人或弄壞東西: 0,
} satisfies Record<Concern, 0>) as Concern[];

const MAX_CONCERNS = 3;
const MAX_NOTE = 200;

/** 1-2 選擇最在意的點：進來時讀回，上一步／下一步都先存檔再換頁。 */
function ConcernsPage() {
  const { id } = Route.useParams();
  return <WithComparison id={id}>{(c) => <ConcernsForm initial={c} />}</WithComparison>;
}

function ConcernsForm({ initial }: { initial: ComparisonOut }) {
  const { id } = Route.useParams();
  const navigate = useNavigate();
  const [concerns, setConcerns] = useState(initial.concerns);
  const [note, setNote] = useState(initial.note);
  const update = useMutation(updateComparisonMutation());
  const [goingNext, setGoingNext] = useState(false);

  const save = (to: "/compare/$id/background" | "/compare/$id/result") => {
    setGoingNext(to === "/compare/$id/result");
    update.mutate(
      { path: { comparison_id: id }, body: { concerns, note } },
      { onSuccess: () => void navigate({ to, params: { id } }) },
    );
  };

  const toggle = (c: Concern) =>
    setConcerns(concerns.includes(c) ? concerns.filter((x) => x !== c) : [...concerns, c]);

  return (
    <main data-page-paper className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead crumb="出發前：幫我選方案 · 2／3" title="選擇最在意的點" />
      <div className={`${card} flex flex-col gap-5`}>
        <h2 className="m-0 t-label text-heading">
          這趟旅行你最擔心什麼？依重要程度點選，最多 3 項。
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 md:gap-4">
          {CONCERNS.map((c) => {
            const order = concerns.indexOf(c) + 1;
            return (
              <ConcernCard
                key={c}
                concern={c}
                order={order}
                disabled={order === 0 && concerns.length >= MAX_CONCERNS}
                onClick={() => toggle(c)}
              />
            );
          })}
        </div>
        <Field label="其他在意的事（選填）" htmlFor="note">
          <textarea
            id="note"
            rows={3}
            maxLength={MAX_NOTE}
            placeholder="例：會去滑雪、帶高價相機"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-describedby="note-hint"
            className={`${fieldInput} w-full`}
          />
          <FieldHint id="note-hint">
            補充說明會納入推薦考量，問答時也會參考。（{note.length}/{MAX_NOTE}）
          </FieldHint>
        </Field>
        {update.error != null && <FieldError>存檔失敗，請再試一次。</FieldError>}
      </div>
      <ActionBar twoColumns>
        <Button
          onClick={() => save("/compare/$id/background")}
          disabled={update.isPending}
          className={btn}
        >
          上一步
        </Button>
        <ActionBar.Push>
          <ActionBar.Full>
            <Button
              onClick={() => save("/compare/$id/result")}
              disabled={concerns.length === 0 || update.isPending}
              className={btnPri}
            >
              下一步
            </Button>
          </ActionBar.Full>
        </ActionBar.Push>
      </ActionBar>
      {(update.isPending || update.isSuccess) && goingNext && (
        <LoadingOverlay>正在比較方案…</LoadingOverlay>
      )}
    </main>
  );
}

import { Button } from "@base-ui/react/button";
import { useMutation } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { updateComparisonMutation } from "../client/@tanstack/react-query.gen";
import type { ComparisonOut, Concern } from "../client/types.gen";
import { WithComparison } from "../features/compare/WithComparison";

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
const buttonClass = "rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50";

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

  const save = (to: "/compare/$id/background" | "/compare/$id/result") =>
    update.mutate(
      { path: { comparison_id: id }, body: { concerns, note } },
      { onSuccess: () => void navigate({ to, params: { id } }) },
    );

  const toggle = (c: Concern) =>
    setConcerns(concerns.includes(c) ? concerns.filter((x) => x !== c) : [...concerns, c]);

  return (
    <main className="max-w-2xl space-y-4">
      <h1 className="text-lg font-bold">這趟旅行你最擔心什麼？依重要程度點選，最多 3 項。</h1>
      <div className="grid grid-cols-3 gap-2">
        {CONCERNS.map((c) => {
          const order = concerns.indexOf(c) + 1;
          return (
            <Button
              key={c}
              aria-pressed={order > 0}
              disabled={order === 0 && concerns.length >= MAX_CONCERNS}
              onClick={() => toggle(c)}
              className="relative min-h-11 rounded-lg border p-2 text-left hover:bg-gray-100 aria-pressed:border-blue-600 aria-pressed:bg-blue-50 data-[disabled]:opacity-40"
            >
              {c}
              {order > 0 && (
                <>
                  <span className="sr-only"> 第 {order} 順位</span>
                  <span
                    aria-hidden
                    className="absolute -top-2 -right-2 grid size-5 place-items-center rounded-full bg-blue-600 text-xs text-white"
                  >
                    {order}
                  </span>
                </>
              )}
            </Button>
          );
        })}
      </div>
      <label className="block">
        其他在意的事（選填）
        <textarea
          rows={2}
          maxLength={MAX_NOTE}
          placeholder="例：會去滑雪、帶高價相機"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          aria-describedby="note-hint"
          className="mt-1 block w-full rounded-md border px-2 py-1"
        />
      </label>
      <p id="note-hint" className="text-sm text-gray-600">
        補充說明會納入推薦考量，問答時也會參考。（{note.length}/{MAX_NOTE}）
      </p>
      {update.error != null && (
        <p role="alert" className="text-red-600">
          存檔失敗，請再試一次。
        </p>
      )}
      <div className="flex gap-2">
        <Button
          onClick={() => save("/compare/$id/background")}
          disabled={update.isPending}
          className={buttonClass}
        >
          上一步
        </Button>
        <Button
          onClick={() => save("/compare/$id/result")}
          disabled={concerns.length === 0 || update.isPending}
          className={buttonClass}
        >
          下一步
        </Button>
      </div>
    </main>
  );
}

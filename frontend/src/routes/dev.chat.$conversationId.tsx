import { Button } from "@base-ui/react/button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { getConversationMessages } from "../client";
import {
  getConversationMessagesQueryKey,
  sendConversationMessageMutation,
} from "../client/@tanstack/react-query.gen";
import type { CitationOut, MessageOut } from "../client/types.gen";

export const Route = createFileRoute("/dev/chat/$conversationId")({
  component: ChatPage,
});

const MAX_LENGTH = 1000; // 同後端 MAX_QUESTION_LENGTH

class NotFoundError extends Error {}
class UnauthorizedError extends Error {}

/** 一則出處：險種、條號、頁碼；展開看條款原文。 */
function Citation({ citation }: { citation: CitationOut }) {
  return (
    <details className="rounded border bg-white px-2 py-1" data-testid="citation">
      <summary className="cursor-pointer">
        {citation.insurance_name} 第 {citation.article_no} 條「{citation.title}」（第{" "}
        {citation.page_start} 頁）
      </summary>
      <p className="mt-1 whitespace-pre-wrap text-sm text-gray-700">{citation.excerpt}</p>
    </details>
  );
}

function Bubble({ message }: { message: MessageOut }) {
  if (message.role === "user") {
    return (
      <li className="flex justify-end" data-testid="message-user">
        <p className="max-w-[80%] whitespace-pre-wrap rounded-lg bg-blue-100 px-3 py-2">
          {message.content}
        </p>
      </li>
    );
  }
  const notCovered = message.citations.length === 0;
  return (
    <li className="space-y-2" data-testid="message-assistant">
      <div
        className={`max-w-[90%] space-y-2 rounded-lg border px-3 py-2 ${notCovered ? "border-amber-400 bg-amber-50" : "bg-gray-50"}`}
      >
        {message.original_only && (
          <p
            data-testid="original-only-badge"
            className="inline-block rounded bg-amber-100 px-2 py-0.5 text-sm text-amber-900"
          >
            條款原文，不是白話說明
          </p>
        )}
        <p className="whitespace-pre-wrap" data-testid="assistant-content">
          {message.content}
        </p>
      </div>
      {message.citations.length > 0 && (
        <div className="max-w-[90%] space-y-1">
          <p className="text-sm font-medium">出處</p>
          {message.citations.map((c) => (
            <Citation key={c.rule_id} citation={c} />
          ))}
        </div>
      )}
    </li>
  );
}

/** 開發工具：方案問答測試頁（正式對話頁由 5 號 agent 負責）。一問一答，不串流；回答附出處，數字沒通過檢查時只顯示條款原文。 */
function ChatPage() {
  const { conversationId } = Route.useParams();
  const queryClient = useQueryClient();
  const path = { conversation_id: conversationId };
  const queryKey = getConversationMessagesQueryKey({ path });

  // 自己包 queryFn 是為了分辨 404（找不到或不是自己的）與其他錯誤；使用者的輸入不進 console
  const messages = useQuery({
    queryKey,
    retry: false,
    queryFn: async () => {
      const { data, response } = await getConversationMessages({ path });
      if (response?.status === 401) throw new UnauthorizedError();
      if (response?.status === 404) throw new NotFoundError();
      if (!data) throw new Error("讀取失敗");
      return data;
    },
  });

  const [draft, setDraft] = useState("");
  const send = useMutation({
    ...sendConversationMessageMutation(),
    onSuccess: async () => {
      setDraft("");
      await queryClient.invalidateQueries({ queryKey });
    },
    // 失敗也重讀歷史：對話若已不存在（404），讀取那邊會切到「找不到對話」
    onError: () => queryClient.invalidateQueries({ queryKey }),
  });
  // 送出失敗時保留問題，讓使用者按「重試」
  const pending = send.isPending ? send.variables?.body.content : undefined;

  const submit = (content: string) => send.mutate({ path, body: { content } });
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (content && !send.isPending) submit(content);
  };

  if (messages.error instanceof UnauthorizedError) {
    return (
      <section className="space-y-4">
        <h2 className="text-xl font-bold">請先登入</h2>
        <p role="alert">問答要用登入的帳號。</p>
        <a
          href={`/login?next=${encodeURIComponent(`/dev/chat/${conversationId}`)}`}
          className="inline-block rounded-md border px-3 py-1 hover:bg-gray-100"
        >
          前往登入
        </a>
      </section>
    );
  }

  if (messages.error instanceof NotFoundError) {
    return (
      <section className="space-y-4">
        <h2 className="text-xl font-bold">找不到對話</h2>
        <p role="alert">這個對話不存在，或不是你的對話。</p>
        <Link to="/dev/chat" className="inline-block rounded-md border px-3 py-1 hover:bg-gray-100">
          回方案選擇
        </Link>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <h2 className="text-xl font-bold">問答</h2>
      <p className="text-sm text-gray-600">
        回答只依這份保障的條款原文，條款沒寫的事不會替你補答案。實際能否理賠請向保險公司確認。
      </p>
      {messages.error && !messages.data && (
        <p role="alert" className="text-red-600">
          無法取得對話內容，請重新整理再試。
        </p>
      )}
      {messages.isPending && !messages.error && <p>讀取中…</p>}
      {messages.data && (
        <ol className="space-y-3" data-testid="messages">
          {messages.data.map((m) => (
            <Bubble key={m.id} message={m} />
          ))}
          {pending && (
            <>
              <li className="flex justify-end">
                <p className="max-w-[80%] whitespace-pre-wrap rounded-lg bg-blue-100 px-3 py-2">
                  {pending}
                </p>
              </li>
              <li role="status" data-testid="answer-pending" className="text-gray-600">
                查詢條款中…
              </li>
            </>
          )}
        </ol>
      )}
      <form onSubmit={onSubmit} className="space-y-2">
        <label className="block font-medium" htmlFor="question">
          提問
        </label>
        <textarea
          id="question"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          readOnly={send.isPending}
          maxLength={MAX_LENGTH}
          rows={3}
          className="w-full rounded-md border px-2 py-1"
        />
        {send.error && (
          <p role="alert" className="text-red-600">
            送出失敗，請再試一次。
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="submit"
            disabled={send.isPending || !draft.trim()}
            className="rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50"
          >
            送出
          </Button>
          {send.error && (
            <Button
              onClick={() => send.variables && submit(send.variables.body.content)}
              className="rounded-md border px-3 py-1 hover:bg-gray-100"
            >
              重試
            </Button>
          )}
          <Link to="/dev/chat" className="rounded-md border px-3 py-1 hover:bg-gray-100">
            回方案選擇
          </Link>
        </div>
      </form>
    </section>
  );
}

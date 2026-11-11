import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { sendIncidentMessage } from "../../client";
import type { IncidentContext } from "../../client/types.gen";
import { ActionBar } from "../../components/ui/ActionBar";
import { btn } from "../../components/ui/buttons";
import { PageHead } from "../../components/ui/PageHead";
import { type ChatLine, DescribeChat, FIRST_QUESTION } from "./DescribeChat";
import { errorText, policyMeta, tripTitle, useIncident } from "./shared";

/**
 * 2-2 描述事故（追問中）：事件已建立、5 號還在追問（`incident_type_code` 還沒有值）時的畫面。
 * 問完（有事故類型）就換成 2-3 理賠頁。對話從 `ctx.messages` 來，重新整理後選項與出處都還在（#212）。
 */
export function ClarifyingView({ id, ctx }: { id: string; ctx: IncidentContext }) {
  const { refresh } = useIncident(id);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const messages = ctx.messages ?? [];
  const last = messages.at(-1);
  // 快速選項只在最後一則是 5 號的訊息時顯示：旅客已經回答過的舊問題，選項不再出現
  const quickReplies = last?.role === "assistant" ? (last.quick_replies ?? []) : [];
  const lines: ChatLine[] = [
    { from: "ai", text: FIRST_QUESTION },
    ...messages.map((m) => ({
      from: m.role === "user" ? ("me" as const) : ("ai" as const),
      text: m.content,
      citations: m.citations,
    })),
  ];

  async function send(content: string, mode: "text" | "quick_reply") {
    if (!content.trim() || busy) return;
    setBusy(true);
    setError(null);
    const res = await sendIncidentMessage({
      path: { incident_id: id },
      body: { content, input_mode: mode },
    });
    if (!res.data) {
      setBusy(false);
      return setError(errorText(res.error, res.response?.status));
    }
    // 回應裡的事件是送出當下的快照，不能直接蓋掉快取，改成重新讀取（5 號回覆可能很慢）
    await refresh();
    setText("");
    setBusy(false);
  }

  return (
    <main data-page-paper className="mx-auto flex max-w-[1040px] flex-col gap-6 font-ui md:px-6">
      <PageHead
        crumb="出事了：幫我處理理賠 · 描述事故"
        title={tripTitle(ctx.destination, ctx.policy.start_date, ctx.policy.end_date)}
        meta={policyMeta(ctx.policy.plan_name, ctx.policy.sum_insured)}
      />
      {error && (
        <p
          role="alert"
          className="m-0 rounded-btn bg-danger-soft px-4 py-2 t-caption-bold text-danger-ink"
          data-testid="error"
        >
          {error}
        </p>
      )}

      <DescribeChat
        busyOverlay="正在整理理賠項目…"
        lines={lines}
        quickReplies={quickReplies}
        placeholder={quickReplies.length > 0 ? "回答上面的問題，或點選項" : "回答上面的問題"}
        value={text}
        onChange={setText}
        busy={busy}
        onSend={(content, mode) => void send(content, mode)}
      />

      <ActionBar>
        <ActionBar.Push>
          <Link to="/" className={btn}>
            回首頁
          </Link>
        </ActionBar.Push>
      </ActionBar>
    </main>
  );
}

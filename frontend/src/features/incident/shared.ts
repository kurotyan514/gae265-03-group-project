import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getIncidentOptions } from "../../client/@tanstack/react-query.gen";
import type { IncidentContext, IncidentReply } from "../../client/types.gen";

export const box = "space-y-2 rounded-md border p-3";
export const input = "rounded-md border px-2 py-1";
export const primary = "rounded-md bg-gray-900 px-3 py-1 text-white disabled:opacity-50";
export const secondary = "rounded-md border px-3 py-1 hover:bg-gray-100 disabled:opacity-50";

/**
 * 後端錯誤轉成給使用者看的句子。
 * 502 是 agent 的回傳不符合契約，細節只在後端 log，不顯示給使用者。
 */
export function errorText(error: unknown, status?: number): string {
  if (status === 502) return "系統暫時無法處理，請稍後再試。";
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "填的內容格式不正確，請檢查後再送出。";
  return status ? `發生錯誤（HTTP ${status}），請稍後再試。` : "連不到伺服器，請稍後再試。";
}

/** 事件；三個步驟頁共用同一份快取，任何一頁更新後其他頁立即看到。 */
export function useIncident(id: string) {
  const queryClient = useQueryClient();
  const options = getIncidentOptions({ path: { incident_id: id } });
  const query = useQuery(options);
  const setIncident = (ctx: IncidentContext) => queryClient.setQueryData(options.queryKey, ctx);
  /** 標成過期並重新讀取；回應是舊快照時（例如慢的 5 號回覆）用這個，免得蓋掉別頁較新的資料。 */
  const refresh = () => queryClient.invalidateQueries({ queryKey: options.queryKey });
  return { ...query, setIncident, refresh };
}

const replyKey = (id: string) => ["incident-reply", id];

/** 5 號最近一次的回覆（快速回覆、出處）；只存在這個分頁，重新整理後就沒有。 */
export function useLatestReply(id: string) {
  const queryClient = useQueryClient();
  const { data } = useQuery<IncidentReply | null>({
    queryKey: replyKey(id),
    queryFn: () => null,
    enabled: false,
    initialData: null,
  });
  return { reply: data, setReply: (r: IncidentReply) => queryClient.setQueryData(replyKey(id), r) };
}

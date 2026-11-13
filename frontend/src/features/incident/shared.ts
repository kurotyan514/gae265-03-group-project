import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getIncidentOptions } from "../../client/@tanstack/react-query.gen";
import type { IncidentContext } from "../../client/types.gen";
import { btnSm, btnSmPri } from "../../components/ui/buttons";
import { fieldInput } from "../../components/ui/Field";
import { wan } from "../../lib/format";

/**
 * 功能二各頁共用的樣式常數，已換成設計稿的 token 樣式（#215）。
 * `primary`／`secondary` 是小按鈕（高 36），因為舊按鈕本來就小；各頁依畫板再選 `btn`／`btnPri`。
 */
/** 卡片外觀（不含內部間距，裡面用 flex gap）。 */
export const card =
  "rounded-2xl border border-line/60 bg-white p-5 shadow-card md:rounded-panel md:px-8 md:py-7";
/**
 * 雙欄畫面（2-2、2-3）的外框：手機照舊；桌機（lg 以上）撐出根容器的 max-w-5xl，最寬 1280px，
 * 讓左邊對話不被擠窄。根容器是全站共用，不動它。
 */
export const wideMain =
  "lg:relative lg:left-1/2 lg:w-[min(1280px,calc(100vw-4rem))] lg:max-w-none lg:-translate-x-1/2";

export const box = `space-y-3 ${card}`;
export const input = fieldInput;
export const primary = btnSmPri;
export const secondary = btnSm;

/**
 * 後端錯誤轉成給使用者看的句子。
 * 502 是 agent 的回傳不符合契約，細節只在後端 log，不顯示給使用者。
 */
export function errorText(error: unknown, status?: number): string {
  if (status === 502) return "系統暫時無法處理，請稍後再試。";
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // 後端自己寫的檢查（例如姓名、電話格式）把說明放在 msg 的「Value error, 」後面
    const messages = detail
      .map((item) => (item as { msg?: unknown })?.msg)
      .filter((msg): msg is string => typeof msg === "string" && msg.startsWith("Value error, "))
      .map((msg) => msg.slice("Value error, ".length));
    return messages.length > 0 ? messages.join("；") : "填的內容格式不正確，請檢查後再送出。";
  }
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

const slash = (date: string) => date.replaceAll("-", "/");

/** 頁首標題「日本 2026/07/05～07/10」：目的地加保險期間；同一年的結束日省略年份。 */
export function tripTitle(
  destination: string | null | undefined,
  start?: string | null,
  end?: string | null,
): string {
  const where = destination?.trim() || "這趟旅行";
  if (!start || !end) return where;
  const from = slash(start);
  const to = slash(end);
  return `${where} ${from}～${from.slice(0, 4) === to.slice(0, 4) ? to.slice(5) : to}`;
}

/** 頁首說明「方案 · 400 萬」。 */
export function policyMeta(planName: string, sum?: number | null): string {
  return sum == null ? planName : `${planName} · ${wan(sum)}`;
}

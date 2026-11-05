// Google 登入與授權（ADR-0020）的共用工具。
// 登入與授權都要整頁導向 Google，所以用一般連結，不用 API client 在背景呼叫。

/** 授權的目的：drive 存理賠文件，gmail 建立草稿與寄信。 */
export type GooglePurpose = "drive" | "gmail";

/** 按「使用 Google 登入」要前往的網址；next 是登入後要回到的站內頁面。 */
export function googleLoginUrl(next: string): string {
  return `/api/v1/auth/google/login?${new URLSearchParams({ next })}`;
}

/** 同意用途說明後要前往的網址；next 是授權後要回到的站內頁面。 */
export function googleAuthorizeUrl(purpose: GooglePurpose, next: string): string {
  return `/api/v1/auth/google/authorize?${new URLSearchParams({ purpose, next })}`;
}

/** 後端導回 /login?error=<代碼> 時顯示的原因。 */
const LOGIN_ERRORS: Record<string, string> = {
  cancelled: "你在 Google 取消了登入。",
  state_mismatch: "登入連結已失效，請重新登入。",
  google_failed: "Google 登入暫時失敗，請稍後再試。",
  email_unverified: "這個 Google 帳號的 email 尚未驗證，請先到 Google 完成驗證再登入。",
};

export function loginErrorMessage(code: string): string {
  return LOGIN_ERRORS[code] ?? "登入失敗，請再試一次。";
}

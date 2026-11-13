import { useEffect, useState } from "react";

// 授權完後端導回原頁時帶的 google_auth=<結果>（ADR-0020）。
const RESULTS: Record<string, { ok: boolean; text: string }> = {
  granted: { ok: true, text: "已完成 Google 授權。" },
  cancelled: { ok: false, text: "你在 Google 取消了授權，需要時可以再按一次。" },
  account_mismatch: {
    ok: false,
    text: "授權時用的 Google 帳號和登入的帳號不同，請改用登入的帳號授權。",
  },
  google_failed: { ok: false, text: "Google 授權暫時失敗，請稍後再試。" },
  state_mismatch: { ok: false, text: "授權連結已失效，請再試一次。" },
  not_google_login: { ok: false, text: "要用 Google 登入的帳號才能授權，請先改用 Google 登入。" },
};

const PARAM = "google_auth";

/** 讀出網址上的授權結果，並從網址拿掉，重新整理時才不會再顯示一次。 */
function takeResultFromUrl(): string | null {
  const url = new URL(window.location.href);
  const code = url.searchParams.get(PARAM);
  if (code !== null) {
    url.searchParams.delete(PARAM);
    window.history.replaceState(window.history.state, "", url);
  }
  return code;
}

/**
 * 顯示從 Google 授權回來的結果；網址上沒有結果時什麼都不顯示。
 * `grantedText` 換掉成功時的說法（例如送件頁只會要 Gmail 授權）。
 */
export function GoogleAuthResult({ grantedText }: { grantedText?: string } = {}) {
  const [code] = useState(() => new URL(window.location.href).searchParams.get(PARAM));
  useEffect(() => {
    takeResultFromUrl();
  }, []);
  if (code === null) return null;
  const known = RESULTS[code];
  const result =
    code === "granted" && grantedText
      ? { ok: true, text: grantedText }
      : (known ?? { ok: false, text: "Google 授權沒有完成，請再試一次。" });
  return (
    <p
      role={result.ok ? "status" : "alert"}
      className={`m-0 rounded-btn px-4 py-2 t-caption-bold ${result.ok ? "bg-leaf-soft text-leaf-text" : "bg-danger-soft text-danger-ink"}`}
      data-testid="google-auth-result"
    >
      {result.text}
    </p>
  );
}

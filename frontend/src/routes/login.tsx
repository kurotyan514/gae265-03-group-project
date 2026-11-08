import { Button } from "@base-ui/react/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import illus from "../assets/illus.jpg";
import { authConfigOptions, devLoginMutation } from "../client/@tanstack/react-query.gen";
import { btnSm } from "../components/ui/buttons";
import { Field, fieldInput } from "../components/ui/Field";
import { googleLoginUrl, loginErrorMessage } from "../features/google/google";

type LoginSearch = { next?: string; error?: string };

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    next: typeof search.next === "string" ? search.next : undefined,
    error: typeof search.error === "string" ? search.error : undefined,
  }),
  component: LoginPage,
});

/** 登入後要回去的頁面：只接受站內路徑，避免被帶去別的網站。 */
function safeNext(next: string | undefined): string {
  return next?.startsWith("/") && !next.startsWith("//") && !next.includes("\\")
    ? next
    : "/account";
}

const contentWidth = "w-[min(462px,100%)]";

/** 登入頁大 Logo（DESIGN.md 5.2）：「好險有你」加左上角三道黃色筆觸與字下方的黃色手繪底線。 */
function BrandLogo() {
  return (
    <h1 className="relative m-0 inline-block py-[22px] pr-1.5 pl-[30px] text-[50px] leading-none font-bold tracking-[0.06em] whitespace-nowrap text-brand md:py-7 md:pl-10 md:text-[72px]">
      <svg
        viewBox="0 0 52 46"
        aria-hidden="true"
        className="absolute top-0 left-0 h-[34px] w-[38px] md:h-[46px] md:w-[52px]"
      >
        <g stroke="#ffba00" strokeWidth="6" strokeLinecap="round" fill="none">
          <path d="M4 30l13 6M17 14l11 12M38 3l4 17" />
        </g>
      </svg>
      好險有你
      <svg
        viewBox="0 0 100 18"
        preserveAspectRatio="none"
        aria-hidden="true"
        className="absolute right-0 bottom-0 h-[18px] w-[62%]"
      >
        <path
          d="M2 11C25 5 62 4 98 8"
          stroke="#ffba00"
          strokeWidth="5"
          strokeLinecap="round"
          fill="none"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
    </h1>
  );
}

/** Google 的「G」標誌（四色）。 */
function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="size-[22px]">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

/**
 * 0-2 登入（DESIGN.md 7.1）：滿版兩欄，左邊插畫、右邊大 Logo、標語與 Google 登入鈕；手機上圖下文。
 * 根外框有 `max-w-5xl p-6`，所以這一頁自己蓋滿畫面。測試登入只在後端明確打開（非正式環境）時，
 * 縮成 Google 鈕下面的一個小區塊；正式環境一定是只有 Google。
 */
function LoginPage() {
  const { next, error } = Route.useSearch();
  const { data: config, error: configError } = useQuery(authConfigOptions());
  const target = safeNext(next);

  return (
    <main className="fixed inset-0 z-10 grid grid-rows-[auto_1fr] overflow-auto bg-paper font-ui md:grid-cols-2 md:grid-rows-1">
      <div className="h-[292px] overflow-hidden md:h-auto">
        <img
          src={illus}
          alt=""
          className="size-full object-cover object-[center_62%] md:object-center"
        />
      </div>
      <div className="flex flex-col items-center justify-start px-6 pt-9 pb-12 text-center md:justify-center md:py-16">
        <BrandLogo />
        <p className="m-0 mt-7 t-login-subtitle text-heading md:mt-9">
          出發前幫你選方案，出事時幫你處理理賠。
        </p>
        {error && (
          <p
            role="alert"
            className={`m-0 mt-6 ${contentWidth} rounded-btn bg-danger-soft px-4 py-2 t-caption-bold text-danger-ink`}
            data-testid="login-error"
          >
            {loginErrorMessage(error)}
          </p>
        )}
        {configError && (
          <p role="alert" className="m-0 mt-6 t-caption-bold text-danger">
            無法取得登入設定，請確認後端有在執行。
          </p>
        )}
        {config && !config.google_login && !config.dev_login && (
          <p className="m-0 mt-6 t-body text-muted">登入功能尚未開放，請聯絡管理者。</p>
        )}
        {config?.google_login && (
          // 一般連結：整頁導向後端，再由後端導向 Google
          <a
            href={googleLoginUrl(target)}
            data-testid="google-login"
            className={`mt-9 flex h-[52px] ${contentWidth} items-center justify-center gap-3 rounded-full bg-white t-caption-bold text-heading shadow-button-raised focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-leaf md:mt-10`}
          >
            <GoogleG />
            <span aria-hidden="true" className="h-[22px] w-px bg-line" />
            使用 Google 帳號登入
          </a>
        )}
        {config?.dev_login && !config.google_login && (
          <p className="m-0 mt-6 t-caption text-muted">
            Google 登入還沒設定（需要 GOOGLE_CLIENT_ID、GOOGLE_CLIENT_SECRET、PUBLIC_BASE_URL、
            TOKEN_ENCRYPTION_KEY，見 .env.example）。
          </p>
        )}
        {config?.dev_login && <DevLoginForm target={target} />}
      </div>
    </main>
  );
}

/** 測試登入：只有後端明確打開時才顯示（任何 email 都能登入）。 */
function DevLoginForm({ target }: { target: string }) {
  const [email, setEmail] = useState("");
  const login = useMutation({
    ...devLoginMutation(),
    // 整頁跳轉：守門的 beforeLoad 會重新向後端確認登入狀態
    onSuccess: () => window.location.assign(target),
  });

  return (
    <form
      className={`mt-8 flex ${contentWidth} flex-col gap-3 rounded-btn border border-dashed border-line bg-white p-4 text-left`}
      onSubmit={(e) => {
        e.preventDefault();
        login.mutate({ body: { email } });
      }}
    >
      <p className="m-0 t-caption text-muted">測試登入（僅開發環境）</p>
      <Field label="Email" htmlFor="dev-login-email">
        <input
          id="dev-login-email"
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={fieldInput}
        />
      </Field>
      {login.error && (
        <p role="alert" className="m-0 t-caption-bold text-danger">
          登入失敗，請確認 Email 格式。
        </p>
      )}
      <Button type="submit" disabled={login.isPending} className={`${btnSm} self-start`}>
        測試登入
      </Button>
    </form>
  );
}

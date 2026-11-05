import { Button } from "@base-ui/react/button";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { authConfigOptions, devLoginMutation } from "../client/@tanstack/react-query.gen";
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

const buttonClass =
  "inline-block rounded-md border px-3 py-1 hover:bg-gray-100 data-[disabled]:opacity-50";

function LoginPage() {
  const { next, error } = Route.useSearch();
  const { data: config, error: configError } = useQuery(authConfigOptions());
  const target = safeNext(next);

  return (
    <main className="mx-auto max-w-sm space-y-4">
      <h1 className="text-2xl font-bold">登入</h1>
      {error && (
        <p role="alert" className="text-red-600" data-testid="login-error">
          {loginErrorMessage(error)}
        </p>
      )}
      {configError && (
        <p role="alert" className="text-red-600">
          無法取得登入設定，請確認後端有在執行。
        </p>
      )}
      {config && !config.google_login && !config.dev_login && (
        <p>登入功能尚未開放，請聯絡管理者。</p>
      )}
      {config?.google_login && (
        // 一般連結：整頁導向後端，再由後端導向 Google
        <a href={googleLoginUrl(target)} className={buttonClass} data-testid="google-login">
          使用 Google 登入
        </a>
      )}
      {config?.dev_login && <DevLoginForm target={target} />}
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
      className="space-y-2 rounded-md border border-dashed p-3"
      onSubmit={(e) => {
        e.preventDefault();
        login.mutate({ body: { email } });
      }}
    >
      <p className="text-sm text-gray-600">測試登入（僅開發環境）</p>
      <label className="block">
        Email
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1 block w-full rounded-md border px-2 py-1"
        />
      </label>
      {login.error && (
        <p role="alert" className="text-red-600">
          登入失敗，請確認 Email 格式。
        </p>
      )}
      <Button type="submit" disabled={login.isPending} className={buttonClass}>
        測試登入
      </Button>
    </form>
  );
}

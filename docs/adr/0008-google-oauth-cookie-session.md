---
status: accepted
---

# 使用者登入用 Google OAuth，由後端走 Authorization Code flow，session 用簽章 cookie

保單文件、對話與理賠案件都是個人資料，必須綁定使用者。登入由後端走 Google 的 Authorization Code flow（Authlib），端點放 `/api/v1/auth/google/*`；成功後發一個簽章的 httpOnly、SameSite=Lax cookie 當 session。前端經 Vite proxy（開發）與 Caddy（正式）與後端同源，不處理 CORS。這是 [ADR-0006](0006-insurance-agent-migration-decisions.md) D7 說的「正式登入另開 ADR」：後台仍用 `ADMIN_TOKEN`，這份只管一般使用者。

- `user` 表存 `google_sub`（唯一）、email、name；其他資料表一律以 `user_id` 關聯，不存 Google 的任何 token。
- scope 只要 `openid email profile`，不需要 Google 審核。日後把原檔存進使用者的 Google Drive 要加 `drive.file`，那是另一份決定（見 [ADR-0009](0009-policy-document-personal-data.md)）。
- 可選的 `ALLOWED_EMAILS` 白名單，留空代表任何 Google 帳號都能登入。
- 非 production 另有 `/auth/dev-login`；測試用 dependency override 換身分；`VITE_MOCK` 模式假登入。production 不註冊 dev-login。
- 新設定（`GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`SESSION_SECRET`、`ALLOWED_EMAILS`）同步到 `config.py`、`.env.example`、`.env.prod.example`。

## Considered Options

- **後端 Authorization Code flow + 簽章 cookie**（採用）：token 不經過瀏覽器的 JavaScript；少一個前端套件。代價是 redirect URI 要在 Google Cloud 逐一登記，ngrok 這類會變的網域每次都要補登記。
- **前端 Google Identity Services 拿 ID token 再給後端驗**：前端要多一套 SDK，後端仍得自己發 session，沒有省事。
- **無狀態 JWT 放 localStorage**：容易被 XSS 讀走，也無法在伺服器端撤銷。
- **匿名 token（原型做法）**：換裝置就看不到資料，也沒辦法對應到使用者自己的 Google Drive。

## Consequences

- 簽章 cookie 沒有伺服器端的 session 表，無法單獨撤銷一個 session；要登出所有裝置得換 `SESSION_SECRET`。需要撤銷時再改成 session 表。
- 本機與 CI 不連 Google；跑 e2e 與測試一律走 dev-login 或 dependency override。

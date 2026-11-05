# Google 登入移除說明（給之後接 Google OAuth 的人）

給要重新做「正式環境登入」或「Google 授權（Drive、Gmail）」的成員，以及你們使用的 AI 助手。
5、6、7 號 agent 的開發者請看 [README.md](README.md) 的「登入與 Google 授權的變更」，不需要讀這份。

## 發生了什麼

`refactor/remove-google-login` 把 Google 登入從程式移除，其餘維持原樣。**這不是決定不用 Google**，只是先拿掉，之後由負責的人用新的設計接回來。

| | 狀態 |
| --- | --- |
| `/auth/google/login`、`/auth/google/callback`、Authlib（`authlib`、`joserfc`） | **已移除** |
| 設定 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`、`ALLOWED_EMAILS`、`PUBLIC_BASE_URL` | **已移除**（`.env.example`、`.env.prod.example` 同步） |
| `core/auth.py` 的 `oauth`、`is_email_allowed`、`safe_next_path` | **已移除** |
| `AuthConfig.google` 欄位、登入頁的 Google 按鈕與錯誤代碼 | **已移除**，前端 client 已重新產生 |
| 簽章 cookie session（`SESSION_SECRET`、`SessionMiddleware`） | 保留 |
| 測試登入 `POST /auth/dev-login`（非 production 且 `DEV_LOGIN_ENABLED=true`） | 保留 |
| `current_user`／`CurrentUser`、`/auth/me`、`/auth/logout` | 保留 |
| `identity` 表、`upsert_user(session, provider, provider_user_id, email, name)` | `user.google_sub` 已移除，改存 `identity`（測試登入 `provider='dev'`） |
| `GoogleAccess`（`contracts/common.py`）、`UnavailableGoogleAccess`（`agents/registry.py`） | 保留，行為不變 |

## 現在的缺口

- **正式環境沒有可用的登入方式**。`dev-login` 在 production 永遠無效，所以部署後 `plans`、`policies`、`incidents` 的路由都會回 401。登入方式已經決定（[ADR-0020](../../adr/0020-google-login-and-incremental-authorization.md)），實作照 [google-login-and-incremental-authorization.md](google-login-and-incremental-authorization.md)。
- **沒有任何 Google 授權的取得與保管**。`GoogleAccess.access_token(user, scope)` 目前一律回 `None`，6 號會回 `needs_review`、7 號會回 `failed`（理由是「請使用者先授權」）。
- `user.google_sub` 已移除，登入身分搬到 `identity`（`provider`、`provider_user_id`，一人一筆）。Google 授權在 `google_grant`（只存加密後的 refresh token）。

## 舊實作在哪裡

程式在 git 歷史裡，移除前的最後一版是 `c666509`（當時的 `origin/main`）：

```bash
git show c666509:backend/app/api/routes/auth.py     # 兩個 Google 端點
git show c666509:backend/app/core/auth.py           # Authlib client、白名單、safe_next_path
git show c666509:backend/tests/test_auth_api.py     # 對應的測試
git show c666509:docs/adr/0008-google-oauth-cookie-session.md   # 當時的完整決策
```

舊實作的做法（ADR-0008）：後端走 Authorization Code flow，scope 只有 `openid email profile`，成功後發簽章的 httpOnly、SameSite=Lax cookie；redirect URI 用 `PUBLIC_BASE_URL` 組，不從請求的 Host 推（經 Vite proxy 或 ngrok 時 Host 不對）；`next` 只接受站內路徑。我們沒有留下它在真實 Google 帳號完成 callback 的驗證紀錄，接回來時要自己實測。

## 已定案的事

以下由 [ADR-0020](../../adr/0020-google-login-and-incremental-authorization.md) 決定，實作細節與測試切點見 [google-login-and-incremental-authorization.md](google-login-and-incremental-authorization.md)。

1. **正式環境用什麼登入**：只用 Google 登入，scope 只有 `openid email profile`；Google 回傳的 email 未驗證時拒絕登入。測試登入保留給非 production。
2. **登入和授權要不要分開**：分開。在上傳理賠文件的畫面按「選擇檔案」時才請求 `drive.file`，按「好險有你小助理幫我送出」時才請求 `gmail.compose`（建立草稿與寄信都用它）；送出要從 Drive 讀附件，所以送出前 Drive 不能用就先授權 Drive，再授權 Gmail；不請求任何 readonly scope。授權回來的帳號必須和登入的同一個。
3. **token 存哪裡、怎麼加密、怎麼撤銷**：存在 `google_grant`，refresh token 用 `TOKEN_ENCRYPTION_KEY` 加密，access token 不存。取消授權時呼叫 Google 撤銷、清空 token、狀態改成 revoked，紀錄保留。
4. **`google_sub` 的去向**：已拆成 `identity` 表。
5. **白名單**：不設 `ALLOWED_EMAILS`。OAuth App 維持 Testing 狀態，能登入的帳號由 Google Cloud 的測試使用者名單控制；後台的 `ADMIN_EMAILS` 是另一件事。

## 接回來時請保持不變的介面

- `CurrentUser`、`current_user`：所有受保護路由與 5、6、7 的 `UserContext(user_id, email)` 都從它來。
- `GoogleAccess` Protocol：實作它，再改 `agents/registry.py` 的 `get_google_access()`，不用改 6、7 號的程式。沒有授權時繼續回 `None`，不要丟例外。
- 測試與 e2e 仍然不連 Google：用 `dependency_overrides[current_user]` 或 `dev-login`。

## 驗證清單

**自動化（不連 Google）**
- [ ] `make test`、`make lint` 全過；`test_operation_ids_are_unique` 不能被新路由弄壞
- [ ] 改了路由就 `make client`，並確認前端登入頁；`make e2e` 全過（用測試登入）
- [ ] production 缺設定時後端啟動即報錯（參考 `check_auth_settings`）
- [ ] 新設定同步 `config.py`、`.env.example`、`.env.prod.example`
- [ ] 沒有 token、使用者 email 或個資寫進 log

**手動（用自己固定的、已加進測試使用者名單的帳號；本機一次、部署後一次）**
- [ ] 登入：導向 Google、選帳號、callback、`/auth/me` 回傳自己的 email；登出後 `/auth/me` 回 401
- [ ] Drive：在上傳理賠文件的畫面按「選擇檔案」→ 用途說明 → 授權 → 上傳一份文件，到自己的 Drive 確認檔案在系統建立的資料夾裡
- [ ] Gmail：按「好險有你小助理幫我送出」→ 用途說明 → 授權 → 建立草稿，到自己的 Gmail 確認草稿與附件
- [ ] 送出時 Drive 已失效：先取消授權，再按「好險有你小助理幫我送出」→ 依序授權 Drive、Gmail → 建立草稿，確認附件還讀得到之前存進 Drive 的檔案
- [ ] 取消授權：按「取消 Google 授權」，到 Google 帳號的「第三方存取權」確認已經沒有這個 App

## 給 AI 助手的起手提示

> 你在協助我重新實作旅遊保險助手專案的正式環境登入（或 Google 授權）。請先閱讀：`docs/agents/handoff/google-login.md`、`docs/agents/handoff/google-login-and-incremental-authorization.md`、`docs/adr/0020-google-login-and-incremental-authorization.md`、`docs/adr/0008-google-oauth-cookie-session.md`、`docs/adr/0009-policy-document-personal-data.md`、`docs/adr/0015-agent-handoff-contracts.md`、`backend/app/api/deps.py`、`backend/app/contracts/common.py`。
> 規則：回答用繁體中文與台灣用語；不要改 `backend/app/contracts/` 的介面；沿用 `CurrentUser`；已 commit 的 migration 不修改，用新 migration；token 與個資不進 log；測試不連 Google。
> 工作方式：先用 `make doctor` 確認環境；照 ADR-0020 與 google-login-and-incremental-authorization.md 實作，spec 沒寫到的事先和我討論，不要自己決定；commit 前先把訊息與檔案清單給我確認。

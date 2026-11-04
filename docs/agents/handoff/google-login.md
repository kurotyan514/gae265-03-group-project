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
| `user.google_sub` 欄位與唯一索引、`upsert_user(session, google_sub, …)` | 保留（測試登入把 `dev:<email>` 存在這裡） |
| `GoogleAccess`（`contracts/common.py`）、`UnavailableGoogleAccess`（`agents/registry.py`） | 保留，行為不變 |

## 現在的缺口

- **正式環境沒有可用的登入方式**。`dev-login` 在 production 永遠無效，所以部署後 `plans`、`policies`、`incidents` 的路由都會回 401。這是接下來最需要決定的事。
- **沒有任何 Google 授權的取得與保管**。`GoogleAccess.access_token(user, scope)` 目前一律回 `None`，6 號會回 `needs_review`、7 號會回 `failed`（理由是「請使用者先授權」）。
- `user.google_sub` 的名字已經不準確（測試登入存的不是 Google 的 sub）。要改名或重新設計要寫新 migration；已 commit 的 migration 不能改。

## 舊實作在哪裡

程式在 git 歷史裡，移除前的最後一版是 `c666509`（當時的 `origin/main`）：

```bash
git show c666509:backend/app/api/routes/auth.py     # 兩個 Google 端點
git show c666509:backend/app/core/auth.py           # Authlib client、白名單、safe_next_path
git show c666509:backend/tests/test_auth_api.py     # 對應的測試
git show c666509:docs/adr/0008-google-oauth-cookie-session.md   # 當時的完整決策
```

舊實作的做法（ADR-0008）：後端走 Authorization Code flow，scope 只有 `openid email profile`，成功後發簽章的 httpOnly、SameSite=Lax cookie；redirect URI 用 `PUBLIC_BASE_URL` 組，不從請求的 Host 推（經 Vite proxy 或 ngrok 時 Host 不對）；`next` 只接受站內路徑。我們沒有留下它在真實 Google 帳號完成 callback 的驗證紀錄，接回來時要自己實測。

## 重新做的時候要決定的事

1. **正式環境用什麼登入**：Google、email 加密碼、magic link，或其他。決定後寫新的 ADR，並在 ADR-0008 補上取代關係（它現在標為 partially superseded）。
2. **要不要把「登入」和「授權 Drive、Gmail」分開**。登入只需要 `openid email profile`，不用 Google 審核；`drive.file` 與 `gmail.send` 需要審核，而且要另外保管 refresh token（目前 `user` 表不存任何 Google token）。分兩步請求比較不會讓一般登入被審核卡住。
3. **token 存哪裡、怎麼加密、怎麼撤銷**：這是個資，要符合 [ADR-0009](../../adr/0009-policy-document-personal-data.md)。
4. **`google_sub` 的去向**：沿用、改名，或拆成 identity 表。
5. **白名單**：是否還需要 `ALLOWED_EMAILS` 這類限制（#47 提到後台第一階段用 `ADMIN_EMAILS`，是另一件事，別混在一起）。

## 接回來時請保持不變的介面

- `CurrentUser`、`current_user`：所有受保護路由與 5、6、7 的 `UserContext(user_id, email)` 都從它來。
- `GoogleAccess` Protocol：實作它，再改 `agents/registry.py` 的 `get_google_access()`，不用改 6、7 號的程式。沒有授權時繼續回 `None`，不要丟例外。
- 測試與 e2e 仍然不連 Google：用 `dependency_overrides[current_user]` 或 `dev-login`。

## 驗證清單

- [ ] `make test`、`make lint` 全過；`test_operation_ids_are_unique` 不能被新路由弄壞
- [ ] 改了路由就 `make client`，並確認前端登入頁
- [ ] 用真實帳號走完整流程：導向 Google、選帳號、callback、`/auth/me`、登出
- [ ] production 缺設定時後端啟動即報錯（參考 `check_auth_settings`）
- [ ] 新設定同步 `config.py`、`.env.example`、`.env.prod.example`
- [ ] 沒有 token、使用者 email 或個資寫進 log

## 給 AI 助手的起手提示

> 你在協助我重新實作旅遊保險助手專案的正式環境登入（或 Google 授權）。請先閱讀：`docs/agents/handoff/google-login.md`、`docs/adr/0008-google-oauth-cookie-session.md`、`docs/adr/0009-policy-document-personal-data.md`、`docs/adr/0015-agent-handoff-contracts.md`、`backend/app/api/deps.py`、`backend/app/contracts/common.py`。
> 規則：回答用繁體中文與台灣用語；不要改 `backend/app/contracts/` 的介面；沿用 `CurrentUser`；已 commit 的 migration 不修改，用新 migration；token 與個資不進 log；測試不連 Google。
> 工作方式：先用 `make doctor` 確認環境；上面「要決定的事」先和我討論，不要自己決定；commit 前先把訊息與檔案清單給我確認。

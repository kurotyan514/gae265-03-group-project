---
status: accepted
---

# 正式環境只用 Google 登入；Drive 與 Gmail 的授權和登入分開，用到時才請求

取代 [ADR-0008](0008-google-oauth-cookie-session.md)。正式環境需要登入方式，6 號要把理賠文件存進使用者自己的 Google Drive，7 號要用使用者自己的 Gmail 建立草稿或寄出送件信。我們決定只用 Google 登入，登入時只拿基本資料；Drive 與 Gmail 的授權另外請求，而且等使用者按到需要它的按鈕時才請求，讓只來看推薦的使用者不會一登入就被要求開放信箱與雲端硬碟。

**登入**
- 後端走 Authorization Code flow，scope 只有 `openid email profile`，並要求 Google 顯示帳號選擇畫面。每個 Google 帳號就是一位獨立的使用者，不做多帳號綁定。
- 使用者以登入身分（`identity`）識別：提供者 `google`，識別是 Google 的 sub，不是 email。測試登入同樣寫進 `identity`，提供者是 `dev`。
- Google 回傳的 email 未驗證時拒絕登入：後台的管理者以 `ADMIN_EMAILS` 比對使用者的 email（[ADR-0016](0016-admin-writable-backoffice-and-plan-owned-insurances.md)），未驗證的 email 可能被冒用。
- 沿用簽章的 httpOnly、SameSite=Lax cookie session 與 `CurrentUser`。redirect URI 由 `PUBLIC_BASE_URL` 組成（`${PUBLIC_BASE_URL}/api/v1/auth/google/callback`），不從請求的 Host 推；登入與授權共用這一條。登入前要去的頁面用 `next` 帶著，只接受站內路徑。

**授權**
- 在上傳理賠文件的畫面按「選擇檔案」時請求 `drive.file`，按「好險有你小助理幫我送出」時請求 `gmail.compose`。請求前先顯示用途說明。授權要整頁導向 Google，會丟掉已選好的檔案，所以前端在選檔視窗打開之前就要知道有沒有有效的授權。按「好險有你小助理幫我送出」時，7 號要從 Drive 讀出理賠文件當附件，所以 Drive 與 Gmail 都要有效。送件的前提是文件備齊（需上傳的待辦只能靠辨識通過完成，辨識通過的文件已存進 Drive），所以前端先確認文件備齊：沒備齊時使用者要先上傳，Drive 不能用就先授權 Drive（還不請求 Gmail），Drive 可以用就帶他回去上傳；備齊了才檢查 Drive，不能用就先授權 Drive，回來後再授權 Gmail。兩個權限分開請求、各自說明用途，使用者可能連續看到兩次同意畫面。不請求任何 readonly scope，也不追蹤保險公司的回信。
- 授權請求帶 `login_hint`（目前登入的帳號）、`include_granted_scopes` 與離線存取。回來時 Google 的 sub 必須等於該使用者 `identity` 的 sub，不一致就拒絕，不保存任何 token。
- 每位使用者一筆 `google_grant`：保存實際拿到的 scope、加密後的 refresh token（金鑰來自 `TOKEN_ENCRYPTION_KEY`，記金鑰版本）、狀態 active／revoked／invalid。access token 不保存，需要時換發。token、金鑰與使用者 email 不進 log（[ADR-0009](0009-policy-document-personal-data.md)）。
- `GoogleAccess` 契約不變：平台的實作在授權有效且含要求的 scope 時回傳 token；沒有授權、已撤銷、invalid 或缺 scope 時回 `None`；換發遇到 `invalid_grant` 時把狀態標成 invalid 並回 `None`，不丟例外。
- 使用者按「取消 Google 授權」時：呼叫 Google 撤銷、清空 refresh token、狀態改成 revoked，紀錄保留當同意紀錄。使用者 Drive 裡的文件與 Gmail 裡的草稿屬於使用者，系統不動。

**OAuth App**
- 維持 Testing 狀態，不送 Google 審核：只有測試使用者名單上的帳號能登入，由一位指定成員管理名單。開發與正式環境共用一個 Google Cloud 專案，各自登記 redirect URI。
- 自動測試與 e2e 不連 Google；本機開發平常用測試登入與假的 `GoogleAccess`。

## Considered Options

- **登入時一次請求全部權限**：流程最簡單，但每個只來看推薦的使用者都會在登入時看到 Gmail 與 Drive 的授權畫面，Restricted scope 也綁在登入上。沒採用。
- **只用 `gmail.send`、不建立草稿**：scope 範圍較小且屬於 Sensitive，但產品要讓使用者可以選擇在 Gmail 建立草稿、自己按寄出。改用 `gmail.compose`。
- **`drive.readonly` 或 Google Picker**：文件只從使用者的裝置上傳，系統只需要存取自己建立的檔案，`drive.file` 就夠。
- **切到 Production 並送審**：Restricted scope（`gmail.compose`）在伺服器經手資料時還要通過 CASA 資安評估，課程專題不划算；不送審的 Production 又有整個專案 100 位使用者的終身上限。採用 Testing。

## Consequences

- Testing 狀態下，Drive 與 Gmail 的授權約 7 天失效，所以 `google_grant.status=invalid` 是正常流程：6 號回 `needs_review`、7 號回 `failed`（「請使用者先授權」），前端顯示重新授權的按鈕。
- Demo 前要把操作者的 Gmail 加進測試使用者名單，不在名單上的帳號登入時會被 Google 擋下。
- 6 號怎麼取得 Drive 資料夾 id、7 號的建立草稿與以保單為單位打包，屬於各自的契約，不在這份決定裡。

# 規格：7 號 agent（打包寄送）第一版

> 狀態：本機草稿，尚未發到 GitHub Issues（之後開 issue 時套用 `ready-for-agent` 標籤）。
> 依據：契約 v2.0.0（`docs/agents/handoff/contract-changelog.md`）、`docs/agents/handoff/agent-7-package.md`、`docs/agents/handoff/contract-v2-proposal.md` 第 3、4、6 節、ADR-0004、ADR-0015、ADR-0019、ADR-0020，以及 7 號對契約 v2 的確認回覆（2026-11-05）。

## 問題

使用者在事件的待辦都完成之後，需要把理賠文件整理成一封信寄給保險公司。現在平台只有假實作（`FakeClaimPackager`）：信件內容只是事件狀況的條列、不會真的從使用者的 Drive 取檔，也不會用使用者的 Gmail 寄出。使用者沒辦法預覽一封像樣的理賠申請信，也沒辦法真的送件。

## 解法

實作真實的 7 號 agent：
- **整理送件包（build）**：依固定的信件範本，用保單、事件與文件的資料產生主旨、內文與附件清單，讓使用者先預覽。範本的每一格抓得到資料就填入，抓不到就留「（請填寫）」，不用 LLM 產生或潤飾內容。
- **寄出（send）**：使用者確認收件人後，從使用者的 Google Drive 取出附件，用使用者自己的 Gmail 寄出，並回傳寄送結果。沒有授權或 Google 出錯時回傳 `failed` 並說明原因，不丟例外。

第一版對著目前的契約 v2.0 做（一次一個事件）。整張保單送件、拆成多封信與 Gmail 草稿等 v2.1 契約定案後再做（見「範圍外」）。

## 使用者故事

1. 身為使用者，我想在所有待辦都完成後預覽要寄出的理賠信，這樣我能在寄出前確認內容正確。
2. 身為使用者，我想讓信件主旨清楚寫出方案與保險期間，這樣保險公司一眼就知道是哪張保單的理賠。
3. 身為使用者，我想讓信件內文列出保單資訊（公司、方案、保額、保險期間），這樣我不用自己再打一次。
4. 身為使用者，我想讓保額與日期跟我的保單完全一致，這樣不會因為數字錯誤被退件。
5. 身為使用者，我想讓內文的事故摘要寫出事故類型、發生日期、地點與經過，這樣保險公司能快速了解發生什麼事。
6. 身為使用者，我想讓系統抓不到的資料（被保險人姓名、保單號碼、聯絡電話等）在信裡留「（請填寫）」，這樣我知道哪裡要自己補。
7. 身為使用者，我想讓附件只包含辨識通過、或我確認過的文件，這樣不合格或還沒確認的檔案不會被寄出去。
8. 身為使用者，我想讓我確認過的「不確定」文件也能當附件，這樣我手動確認的文件不會被漏掉。
9. 身為使用者，我想讓內文的附件清單跟實際附上的檔案一致，這樣保險公司能對照。
10. 身為使用者，我想讓我自行勾選、沒附文件的待辦在信裡註明「未隨信附上」，這樣保險公司知道這份文件會另外提供。
11. 身為使用者，我想讓整趟行程共用的理賠申請書（D10）只附一次，這樣信裡不會出現重複的申請書。
12. 身為使用者，我想在還有待辦沒完成時被擋下來、看到缺哪幾項，這樣我知道還要做什麼。
13. 身為使用者，我想讓「不適用」的待辦不算在缺漏裡，這樣不會因為不需要的文件而送不出去。
14. 身為使用者，我想讓信由我自己的 Gmail 寄出，這樣保險公司的回覆會直接回到我的信箱。
15. 身為使用者，我想在沒有授權 Gmail 或 Drive 時看到「請先授權」的說明，而不是一個看不懂的錯誤，這樣我知道下一步要做什麼。
16. 身為使用者，我想在授權過期（測試狀態約 7 天）時得到同樣的「請先授權」說明，這樣我重新授權就能繼續。
17. 身為使用者，我想在 Drive 上的檔案被刪掉或拿不到時，看到寄送失敗的原因，這樣我知道要重新上傳。
18. 身為使用者，我想讓寄送失敗時什麼都不寄出，這樣保險公司不會收到缺附件的信。
19. 身為使用者，我想讓附件的檔名是系統取的名字（不是我上傳時的原檔名），這樣檔名不會洩漏我的個人資訊，也比較好辨識。
20. 身為使用者，我想讓信件結尾有「實際能否理賠請以保險公司審核為準」的提醒，這樣我不會誤以為送出就一定會賠。
21. 身為使用者，我想讓信件寫明「如需補件，請直接回覆此信」，這樣保險公司知道怎麼聯絡我。
22. 身為保險公司的理賠人員，我想收到格式固定、資訊完整的理賠信，這樣我能快速處理。
23. 身為保險公司的理賠人員，我想讓附件檔名能看出是哪個事故的哪份文件，這樣我能對照附件清單。
24. 身為 7 號開發者，我想把連 Gmail 與 Drive 的程式集中在一個可替換的轉接器，這樣測試不用連網。
25. 身為 7 號開發者，我想直接對 `build`／`send` 寫測試、自己組事件資料與授權，這樣每條規則都能單獨驗證。
26. 身為 7 號開發者，我想註冊一個只換掉 Gmail／Drive 轉接器的離線版，這樣能跑平台的契約測試而不連 Google。
27. 身為 7 號開發者，我想讓離線版在正式環境拒絕運作，這樣 `.env` 設錯時不會在正式網站「假裝寄出」。
28. 身為 7 號開發者，我想讓公司名稱的取得集中在一個小函式，這樣平台日後把公司名放進契約時，只要改這一處。
29. 身為平台負責人，我想讓 7 號只回傳結果、不碰資料庫，這樣送件紀錄仍由平台驗證後寫入（ADR-0015）。
30. 身為平台負責人，我想讓 7 號的 log 與錯誤訊息不含信件內容與個資，這樣符合 ADR-0009 的個資規則。

## 實作決定

**模組**
- 新增 7 號套件，裡面有：
  - **送件包產生**：把 `IncidentContext` 轉成信件主旨、內文、附件清單與缺漏待辦。純函式、不連網、不用 LLM。
  - **Google 轉接器**：唯一連外的地方，提供「從 Drive 取檔（內容、檔名、大小）」與「用 Gmail 寄信」兩個動作。正式版用 HTTP 呼叫 Google API（Drive v3、Gmail API），離線版在記憶體裡模擬。
  - **公司名稱查詢**：用 `ctx.policy.plan_id` 查方案資料檔（`backend/data/config/plans.json`）的 `company`，7 號自己讀檔，不用平台的 `get_plan`（2026-11-05 決定，讓 7 號的測試不需要平台設定就能跑）。查不到方案、檔案讀不到或格式不對時，公司留「（請填寫）」，其他照常產生，不讓使用者看不到送件包（2026-11-05 決定）。檔案位置用平台的預設位置；平台可用環境變數 `DATA_DIR` 改位置，7 號不跟著改（目前沒有人設）。另有守門測試讀真正的 `plans.json`，檢查每個方案都查得到公司，檔案搬家或格式改了會在 CI 失敗。
  - **`ClaimPackager` 實作**：`build` 呼叫送件包產生；`send` 檢查授權、透過轉接器取檔與寄信、回傳 `SendResult`。
- 在平台的 agent 註冊表註冊兩個名字：
  - **正式版**（暫名 `gmail`）
  - **離線版**（暫名 `gmail-offline`）：只換掉 Google 轉接器，授權照平台給的 `GoogleAccess` 判斷；在正式環境（依平台的環境設定）一被呼叫就報錯，不回傳假的寄送結果。

**契約（不改，對著 v2.0 實作）**
- 輸入是 `IncidentContext`；`send` 另外拿 `ClaimPackage`、收件人、`UserContext` 與 `GoogleAccess`。
- 輸出是 `ClaimPackage`（`subject`、`body`、`attachments`、`missing_todo_ids`、`recipient_hint`）與 `SendResult`（`sent`／`failed`、`external_ref`、`reason`）。

**信件範本**（依 7 號提供的範本，2026-11-05）
- 主旨：`旅遊保險理賠申請－{方案}－{保險期間起}～{保險期間迄}`。只放方案名稱、不放公司名稱，因為平台的方案名稱已經含公司簡稱（例如「富邦國外旅平險-進階型」），再加公司會重複（2026-11-05 決定）。保險期間寫成 `2026/08/10～08/14`（同一年時迄日不寫年份，依 7 號的範本）；跨年時迄日加上年份，例如 `2026/12/30～2027/01/03`；抓不到保險期間時，主旨寫明「（請填寫保險期間）」，內文的保險期間仍留「（請填寫）」（2026-11-05 決定）。
- 內文依序：
  1. 問候與「我是被保險人（請填寫）」
  2. 保單資訊：公司、方案、保額、保險期間、保單號碼（請填寫）
  3. 事故摘要：一個事件一行，格式 `・{事故類型} · {日期} · {地點}：{經過}`，各項分開、不組句子，例如 `・班機延誤 · 2026/08/10 · 日本：我從新加坡搭長榮回台北，…`（2026-11-06 決定）
  4. 未隨信附上的文件：使用者自行勾選、沒附文件（`without_document`）的待辦，一項一行，寫待辦名稱加「（另行提供）」，例如 `・航空公司賠償或處理結果證明（另行提供）`；順序同附件（依待辦順序，理賠申請書 D10 放最後）；沒有這種待辦時整段不出現；放在附件清單前面（2026-11-06 決定）
  5. 附件清單：一個檔案一行（`・{檔名}`），與實際附件用同一份資料、同一個順序（理賠申請書 D10 在最後）；檔名用平台給的 `file_name`（2026-11-06 決定 `build` 維持用它，不改契約從 Drive 讀）
  6. 聯絡電話（請填寫）、「如需補件，請直接回覆此信。」
  7. 免責聲明「實際能否理賠請以保險公司審核為準」：照交接說明規則 5 的原文、不加句號，自成一段，放在信件最後（2026-11-06 決定）
- **資料來源**：方案、保額、保險期間取自 `ctx.policy`。事故摘要（2026-11-06 決定）：事故類型取 `incident_type_name`；日期取 5 號記下的發生日期（`facts` 裡代號 `date`，即事故設定檔共用欄位的代號），看得懂（年/月/日或年-月-日，且日期存在）就寫成 `2026/08/10`，看不懂（例如「不知道」、`2026/13/45`）照抄原文；地點取 `destination`（建立事件時填的旅行目的地，不是事故地點）；經過取 `description`（使用者建立事件時打的第一句描述）全文，照原樣放、不加字。
- **抓不到的資料**：留「（請填寫）」，不猜、不用 LLM 補。主旨與事故摘要寫明是哪一項：主旨「（請填寫保險期間）」；事故摘要「（請填寫事故類型）」「（請填寫日期）」「（請填寫地點）」「（請填寫經過）」。保單資訊仍用「（請填寫）」。
- **數字與日期**：只能來自 `ctx.policy` 與事件資料，由程式排版，不由 LLM 產生（ADR-0004）。保額是萬的整數倍時寫成「600 萬」，1000 萬以上不加逗號（例如「1000 萬」，2026-11-05 決定）；不是萬的整數倍時寫完整金額、不捨去（ADR-0004），例如「6,500,123 元」（2026-11-05 決定）。
- 被保險人、保單號碼、聯絡電話固定留「（請填寫）」，由使用者在信裡自己填。

**附件規則**
- 只取 `ctx.documents` 裡 `recognition_status == "recognized"` 或 `confirmed_by_user` 為真，而且 `storage_path` 不是空的文件。
- 只寄待辦清單要求的文件：文件要屬於 `ctx.todos` 裡的一項待辦；對不到待辦的（使用者沒指定待辦、多傳的文件，6 號辨識通過但 `todo_id` 是空的）不當附件（2026-11-05 決定）。
- 整張保單共用的待辦（`scope == "policy"`，理賠申請書 D10）的文件只附一次（單一事件時本來就只有一次；整張保單送件時才要處理）。
- 排序：依待辦的 `sort_order`，不是上傳順序（平台給的文件依上傳時間排）；D10 放最後（與範本一致），即使它的 `sort_order` 比事件待辦小（平台建 D10 時沿用範本的順序號）；同一項待辦的多份文件維持上傳順序。
- `build` 階段的附件檔名用平台給的 `file_name`（等於 6 號取的名字）；`send` 階段的實際檔名與大小從 Drive 讀。

**缺漏待辦**
- `missing_todo_ids` 是狀態為 `pending` 的待辦。
- `not_applicable` 不算缺漏；使用者自行勾選的 `without_document` 待辦算完成，但在內文列為「未隨信附上」。

**寄送（send）**
- 用 `google.access_token(user, "gmail.compose")` 與 `google.access_token(user, "drive.file")` 取得授權。任一個是 `None` 就回 `failed`，`reason` 寫「請使用者先授權」，並註明缺 Gmail 或 Drive。不丟例外，也不寄出。
- 用 `storage_path`（Drive 檔案編號）向 Drive 取每個附件的內容、檔名與大小，再組成一封信用 Gmail 寄給使用者確認過的收件人。成功回 `sent`，`external_ref` 放 Gmail 回傳的信件編號。
- Google 回錯誤（檔案不存在、授權失效、暫時連不上等）時回 `failed`，`reason` 寫原因的類別，例如「Drive 上找不到附件，請重新上傳」。不丟例外、不寄出部分內容。
- log 與 `reason` 只放編號與錯誤類別，不放信件內容、檔名以外的個資、token 或 email。

**收件人**
- `recipient_hint` 第一版回空值，由使用者輸入收件人。資料來源待決（見「其他說明」）。

## 測試決定

- **好的測試只看對外行為**：給定輸入的事件資料與授權，檢查回傳的送件包或寄送結果、以及假轉接器記錄到「取了哪些檔、寄了什麼」。不測內部函式怎麼拆。
- **接口 ①：7 號的 `build`／`send`**（主要）。在測試裡自己組 `IncidentContext`，配上假的 `GoogleAccess`（沒授權、只有 Gmail、只有 Drive、兩者都有）和假的 Google 轉接器。要涵蓋：
  - 附件只含 `recognized` 或 `confirmed_by_user`；`needs_review`（未確認）、`incomplete`、`failed`、沒有 `storage_path` 的文件不會出現。
  - `without_document` 的待辦列在「未隨信附上」，而且沒有附件。
  - D10 的文件只出現一次，放在最後。
  - `missing_todo_ids` 正確；`not_applicable` 不算缺漏。
  - 主旨與內文裡的每個數字與日期都能在 `ctx.policy` 或事件資料中找到（數字白名單檢查）。
  - 抓不到的資料（例如沒有地點、方案查不到公司）留「（請填寫）」。
  - 沒有授權時 `send` 回 `failed` 且不丟例外，假轉接器沒有寄出任何信。
  - Drive 取檔失敗、Gmail 寄送失敗時回 `failed`，`reason` 不含信件內容。
  - 離線版在正式環境設定下會報錯。
- **接口 ②：Google 轉接器**。正式版只做薄薄一層 HTTP 呼叫，不寫連真的 Google 的自動測試（ADR-0020）。
- **接口 ③：平台的契約測試**（`backend/tests/contracts/`，不修改）。用 `CONTRACT_AGENT_7=gmail-offline make test args="-k contracts"` 跑。
- **真的連 Google**：照 `docs/agents/handoff/google-login.md` 的驗證清單，用測試帳號手動寄一封確認。
- **參考的既有測試**：`backend/tests/contracts/`（`FakeClaimPackager` 與整條流程）、`backend/tests/google/test_google_access.py`（假的 Google 授權）。

## 需要平台處理

1. **契約測試的假授權（也影響 6 號）**：整條流程測試（`test_full_flow_from_message_to_submission`）要求 6 號上傳後是 `recognized`、7 號送件後是 `sent`，但測試環境的 `get_google_access()` 一律回 `None`。6、7 號照交接規則寫（沒授權時 6 回 `needs_review`、7 回 `failed`），真實實作在這個測試會失敗；現在會過是因為假實作不看授權。請平台照提案第 5 節：整條流程給假授權（Drive、Gmail 都有），另加「沒授權」劇本（6 回 `needs_review`、7 回 `failed`、事件不標完成）。6、7 號各自註冊離線版（連 Google 的部分換成假的），契約測試用離線版跑，不會真的連 Google；5 號不受影響（5 號的介面沒有 Google 授權）。**在平台修好之前，7 號這個測試預期會失敗，不修改測試去配合。**（2026-11-06 依群組回覆更新）
2. **v2.1 契約**（依 7 號確認回覆）：
   - 新增 `build_for_policy(policy_ctx)`，`policy_ctx` 含保單、這張保單底下所有事件與其文件、D10 的文件。
   - `AttachmentRef` 加檔案大小（`size_bytes`）。
   - `SendResult` 加 `drafted` 狀態與多個信件編號。
3. **交接說明**：`docs/agents/handoff/agent-7-package.md` 還寫「附件只能是 recognized」，請更新為 v2.0 的「recognized 或使用者確認過」；`access_token` 的說明也還寫一律回 None。

## 範圍外

- LLM 潤飾信件內文（第一版完全用範本）。
- 整張保單送件（`build_for_policy`）、拆成多封信、Gmail 草稿（`drafted`）：等 v2.1 契約定案後另開規格。
- 追蹤保險公司回信（規格 v3.3 不追蹤，ADR-0020 不請求 readonly 權限）。
- 收件人資料表或自動帶入保險公司理賠信箱。
- 前端的預覽與送出畫面。
- 修改契約檔（`backend/app/contracts/`）與契約測試（`backend/tests/contracts/`）。

## 其他說明（待決）

- **收件人從哪來**：交接說明列為待決，ADR-0019 也決定資料庫不存保險公司。第一版由使用者輸入。
- **D10 在多事件時會擋住每個事件送件**：平台先接受（Demo 只有單一事故），多事件的語意等 `build_for_policy` 一起定。

## 相關檔案位置（2026-11-05 撰寫時，之後可能搬動）

**7 號要新增或修改的**
- 7 號套件（實作放這裡）：`backend/app/agents/package/`
- 註冊正式版與離線版：`backend/app/agents/registry.py`（用 `register_claim_packager`）
- 7 號自己的測試：`backend/tests/agents/package/`（建議位置）

**只讀、不修改的**
- 7 號契約：`backend/app/contracts/package_agent.py`（`ClaimPackager`、`ClaimPackage`、`AttachmentRef`、`SendResult`）
- 共用契約：`backend/app/contracts/common.py`（`IncidentContext`、`PolicySummary`、`TodoView`、`DocumentView`、`GoogleAccess`）
- 假實作：`backend/app/contracts/fakes.py`（`FakeClaimPackager`）
- 平台呼叫 7 號的地方：`backend/app/api/routes/incidents.py`（`GET /incidents/{id}/package`、`POST /incidents/{id}/submission`）
- 平台的 Google 授權：`backend/app/core/google_grants.py`、`backend/app/core/google_oauth.py`（scope 常數 `DRIVE_SCOPE`、`GMAIL_SCOPE`）
- 環境設定：`backend/app/core/config.py`
- 方案資料檔（公司名稱）：`backend/data/config/plans.json`
- 契約測試：`backend/tests/contracts/`（`test_flow.py` 的整條流程、`test_v2.py`、`conftest.py` 的 `CONTRACT_AGENT_7`）

**參考文件**
- 7 號交接說明：`docs/agents/handoff/agent-7-package.md`
- 契約變更紀錄：`docs/agents/handoff/contract-changelog.md`
- 契約 v2 提案：`docs/agents/handoff/contract-v2-proposal.md`
- Google 登入驗證清單：`docs/agents/handoff/google-login.md`
- ADR：`docs/adr/0004-llm-never-produces-numbers.md`、`docs/adr/0015-agent-handoff-contracts.md`、`docs/adr/0019-no-insurance-company.md`、`docs/adr/0020-google-login-and-incremental-authorization.md`

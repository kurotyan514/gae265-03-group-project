# 介面契約變更紀錄

5、6、7 號 agent 的契約（`backend/app/contracts/`）、`IncidentContext` 與相關資料表的變更。**新的寫在最上面**。變更契約的人要在這裡加一筆，並更新對應的交接說明（`agent-5/6/7-*.md`）、契約測試與 `make client`。

## 提案（尚未實施）　7 號對 v2.1 之後的契約需求：多封信與 Gmail 草稿的回傳（7 號，2026-11-07）

> **狀態：提案，契約型別沒有改**（`backend/app/contracts/` 仍是 2.1.0）。由 7 號開發者提出，等平台負責人決定；定案後平台改契約時，請把這段換成正式的變更紀錄。
> 依據：#154（7 號建立草稿已接上，見下方「7 號這邊已做的」）、[ADR-0025](../../adr/0025-claim-submission-fill-before-send.md)、`docs/specs/agent-7-package.md`「需要平台處理」第 2 項、`docs/integration-plan.md`「已知契約缺口」的 7 號那條。
> 原則照舊：只新增、有預設值，v2.1 的實作與呼叫方式不改也能跑。

**7 號這邊已做的（不需要改契約）**
- `mode="draft"`：在使用者的 Gmail 建立草稿，回 `drafted`，`external_ref` 是 Gmail 的**草稿編號**（`drafts.create` 回傳的 `id`，不是草稿裡那封信的編號）。有空格也能建，收件者可以沒有；沒有 Gmail 或 Drive 授權時回 `failed`、`reason` 說明要授權哪個。
- 寄出與草稿用同一份主旨、內文與附件；草稿另外加一份把「（請填寫＋項目）」黃底紅字標出的 HTML 版本。附件檔名重複時加「_序號」（#74）。
- 事故摘要的地點：`destination` 沒有時用 5 號記下的事實 `place`（#165）。`place` 已在 `ctx.facts` 裡，這項不需要改契約。

### 1. 多封信（一次送件拆成多封）

**為什麼要**：整張保單送件時附件可能很多，Gmail 一封信（含附件）上限約 25 MB，超過要拆成多封；之後也可能依事件分封。現在 `ClaimPackage` 只有一份主旨與內文、`SendResult` 只有一個 `external_ref`，裝不下多封信的結果。

**提議的欄位**（名稱可由平台調整）
- `AttachmentRef.size_bytes: int | None = None`：附件大小（平台的 `incident_document.size_bytes` 已有）。7 號在 `build` 就能判斷要不要拆，預覽時就讓使用者看到會分幾封；沒有值時 7 號在 `send` 從 Drive 讀大小再判斷。
- `ClaimPackage.letters: list[Letter] = []`，`Letter` 有 `subject`、`body`、`attachments`。空的時候代表只有一封，就是現在的 `subject`／`body`／`attachments`（舊程式照樣能用）；有值時舊的三個欄位放第一封，方便舊畫面顯示。
- `SendResult.letters: list[LetterResult] = []`，`LetterResult` 有 `index`（第幾封，從 0 起）、`status`（`sent`／`drafted`／`failed`）、`external_ref`、`reason`。`SendResult.status` 與 `external_ref` 維持「整體結果」與「第一封的編號」。
- `fills` 套用：平台目前只在 `subject`／`body` 換空格，有 `letters` 時要一起換每一封；7 號會讓同一個項目在每封信寫法一致。

**要平台決定的**
- **部分成功**：第 1 封寄出、第 2 封失敗時怎麼算？7 號建議整體回 `failed`、`letters` 照實列出哪幾封已寄出，平台記 `pending` 不結案，`gmail_refs` 照樣存已寄出的編號；重送時 7 號只寄還沒成功的那幾封（需要平台把上次的 `letters` 結果帶回來，或另加 `already_sent: list[int]` 參數）。避免保險公司收到重複的信。
- **拆封規則誰決定**：建議 7 號決定（純程式、依附件大小與順序，不用 LLM），平台只驗證「所有附件剛好出現一次」「附件都是可附的文件」。
- 送件紀錄：`policy_submission.gmail_refs` 存多個編號的格式（例如 `{"messages": [...], "drafts": [...]}`）。

### 2. Gmail 草稿：建好之後要回傳什麼

**現在**：`drafted` 只回一個草稿編號（`external_ref`），平台寫進 `gmail_refs.draft_id`。送件 API 回 `SubmissionOut.status = drafted`，結案後重新整理就不知道是怎麼結案的（`integration-plan.md`「還沒驗到的部分」最後一條）。

**提議**
- `SendResult.message_id: str | None = None`：草稿裡那封信的編號（`drafts.create` 回的 `message.id`）。寄出時就是 `external_ref`，草稿時兩個不一樣。之後要追蹤使用者有沒有從 Gmail 寄出、或要組 Gmail 網頁連結，需要的是這個編號。
- **連結由平台（或前端）組，不放進契約**：Gmail 沒有正式文件記載的草稿連結格式（目前可用的是 `https://mail.google.com/mail/#drafts?compose=<message_id>`，Google 隨時可能改），而且使用者可能登入多個 Google 帳號，連結會開錯帳號。建議畫面先寫「已存到你的 Gmail 草稿匣」並附 `https://mail.google.com/mail/#drafts`，不保證直接打開那一封。請平台決定要不要另加 `draft_url`。
- **讀事件要能知道送件結果**：`GET /incidents/{id}`（或另一個端點）回傳最近一次送件的 `status`（`sent`／`drafted`／`self_submitted`）與時間，讓結案後的送件頁顯示「已寄出」「已建立草稿」「自己處理」。只回狀態與時間，不回信件內容與 `fills`（ADR-0009）。
- **草稿建好之後不追蹤**：使用者在 Gmail 改了、刪了或寄出了草稿，系統都不知道；規格 v3.3 不追蹤回信，7 號建議 `drafted` 就是最終狀態，平台不輪詢。若之後要追蹤，靠上面的 `message_id`。
- **重複建立**：平台在 `drafted` 後已結案（#152），重按會被 409 擋，7 號不另外防重複。`failed` 代表什麼都沒建，可以重試。

### 3. 預覽時就檢查附件還在不在 Drive（#155 手動驗收 7-2，2026-11-08 使用者選定）

**現象**：使用者在 Google Drive 永久刪除一份理賠文件後，預覽信的附件清單還是列著它，寄出時 7 號才回 `failed`「Google Drive 上找不到…」。照說明重新上傳也沒用：系統裡被刪掉的舊文件還在，下次預覽、寄出仍會帶到它，這個事件就寄不出去。

**原因**：預覽（`GET /incidents/{id}/package` → `build(ctx)`）只讀系統裡的文件紀錄；`build` 拿不到 Google 授權，查不了 Drive。平台也沒有刪除文件的 API。

**提議**（只新增、有預設值）
- `ClaimPackager.build(ctx, google: GoogleAccess | None = None, user: UserContext | None = None)`：多兩個選填參數。平台的預覽 API 帶上目前使用者與 `get_google_access()`；舊的呼叫 `build(ctx)` 照樣能用。
- 有 Drive 授權時，7 號在 `build` 對每個附件讀一次檔案資訊（只讀檔名與是否在垃圾桶，不下載內容）：
  - 還在的照常當附件。
  - 找不到或在垃圾桶的**不放進 `attachments`**，改列在信裡的「未隨信附上的文件」，例如「・班機延誤_機票及登機證…_1.pdf（Google Drive 上找不到，請重新上傳）」「…（在 Google Drive 的垃圾桶裡，請還原）」。附件清單與實際附件仍是同一份資料。
  - 使用者重新上傳後，新文件是附件，舊的那份繼續列在「未隨信附上」直到下次預覽查不到為止；不用刪除文件的 API 也寄得出去。
- 沒有 Drive 授權、或 Google 暫時連不上時，照現在的樣子全部列為附件（不能因為查不到就少附），寄出時 `send` 仍會再檢查一次並回 `failed`。
- **待辦不動**：這個做法不改待辦的勾選狀態，也不改 `incident_todo`、`incident_document` 的資料。

**要平台決定的**
- 預覽 API 是否接受多打幾次 Drive（每個附件一次 metadata 請求，班機延誤通常 3～4 個）。
- `ClaimPackage` 是否加 `unavailable_document_ids: list[uuid.UUID] = []`，讓送件頁在上傳文件頁也能標出「這份在 Drive 上已經找不到」。不加的話只在信裡寫明。
- 7 號這邊等契約定案後再接；在那之前維持寄出時才檢查（已做，見上方「7 號這邊已做的」）。

### 4. 其他（已在 7 號規格，列在這裡方便一起決定）
- `build_for_policy(policy_ctx)`：整張保單送件，`policy_ctx` 含保單、底下所有事件與其文件、D10 的文件；D10 只附一次。
- **契約測試的整條流程**：`test_full_flow_from_message_to_submission` 寄出時只帶 `recipient`、沒帶 `fills`。真的 7 號一定有平台沒有的空格（被保險人姓名、保單號碼、聯絡電話），平台在呼叫 7 號之前就回 409，所以 `CONTRACT_AGENT_7=gmail-offline make test args="-k contracts"` 在 main 上本來就失敗（2026-11-07 確認，跟 #154 的改動無關）。請平台在這個測試帶上 `fills`（項目從預覽的信裡找「（請填寫＋項目）」），並給 Drive、Gmail 的假授權。7 號不改契約測試。

## 2026-11-07　`IncidentContext.occurred_at` 開始有值（契約仍是 2.1.0，#159）

**契約型別沒有改**，只是平台開始填這個欄位：5 號回覆的 `date` 事實（`2026/11/05`、`2026-11-05`、`2026.11.5`、`2026年11月5日`）是完整而真實的日期時，平台把 `occurred_at` 設成那天的 **00:00 UTC**；之後 `date` 事實改了就跟著改，改成「不知道」、沒有年份（`8月10日`）或不存在的日期（`2026/13/45`）就清成 `None`。
- 只有「當地日期」有意義（發生地不一定在台灣），所以固定存 00:00 UTC，取 `.date()` 不會因為時區差一天。要用日期請用 `ctx.occurred_at.date()`，不要拿時間部分。
- 6 號的事故資料夾名稱（「班機延誤 2026-11-05」）本來就讀這個欄位，現在會有日期。7 號仍讀 `date` 事實（它有自己的格式判斷），不受影響。

## 2026-11-06　契約 v2.1.0：7 號建立草稿與送件 API 收 mode／fills／recipient（#151、[ADR-0025](../../adr/0025-claim-submission-fill-before-send.md)）

**版本號**：`CONTRACT_VERSION = "2.1.0"`。**契約（`package_agent.py`）**：只新增、舊的呼叫方式照樣能用。
- `ClaimPackager.send` 多一個 `mode: SendMode`（`"send"` 預設｜`"draft"`），`recipient` 型別改成 `str | None`（`"draft"` 可以沒有）。`SendMode` 從 `app.contracts` 匯出。
- `SendResult.status` 多 `"drafted"`：`external_ref` 放草稿編號。
- `"send"` 時信裡還有「（請填寫＋項目）」就回 `failed`、不寄；`"draft"` 有空格也能建。平台**只有建立草稿才帶 `mode`**，寄出維持舊的呼叫（7 號接上之前不會壞）。
- `FakeClaimPackager` 支援 `"draft"`（回 `drafted`）。`GmailClaimPackager` 目前遇到 `"draft"` 明確回 `failed`「建立草稿功能開發中」，等 #154 接上。

**API**：`POST /incidents/{id}/submission`
- 請求：`mode`（`send` 預設｜`draft`｜`self`）、`fills`（項目 → 值）、`recipient`（`send` 必填且要是信箱格式、`draft` 可以沒有、`self` 不用；不合格回 422）。只有 `recipient` 的舊請求仍當作寄出，不過信裡還有空格就被擋。
- 處理順序：事件已結案 409（#152）→ 待辦沒完成 409 → `self` 不呼叫 7 號，記 `self_submitted` 並結案 → 呼叫 `build`、把 `fills` 放進空格（只換「（請填寫＋項目）」那一段，值去掉頭尾空白，空值視同沒填，信上沒有的項目忽略）→ `send` 時還有空格 409（訊息列出項目）→ 呼叫 7 號。
- 結果：`sent`、`drafted`、`self_submitted` 都結案；7 號回 `failed` 時記 `pending`、不結案。`SubmissionOut.status` 多 `drafted`、`self_submitted`。送件紀錄只存編號與狀態（`gmail_refs` 草稿放 `draft_id`），不存 `fills` 與信件內容。
- `policy_submission` 只改欄位說明，沒有 migration。

**還沒做**：正式送件頁（#153）；7 號真的建立草稿（#154）；整張保單送件（`build_for_policy`）。

## 2026-11-05　契約 v2.0.0（提案見 [contract-v2-proposal.md](contract-v2-proposal.md)）

**版本號**：`CONTRACT_VERSION = "2.0.0"`（`app.contracts`）。原則：**只新增、保留舊欄位**，新欄位都有預設值，v1 的實作不改也能跑。

**5 號**
- `IncidentContext.event_types`（全部事故類型：代號、名稱、必問欄位、這張保單對應的保障 `coverages`）、`common_fields`（每個類型共用的必問欄位）、`major_notices`（重大注意事項，最多 4 條，平台算好，`{start_date}`、`{end_date}` 已帶入保單的日期）。問的過程中類型還沒判斷出來，`follow_up_questions` 仍是空的，靠 `event_types` 問。
- `ClauseUpdate`、`ClauseView` 加 `conclusion`（`applicable`／`excluded`／`insufficient`）與 `amount_note`。沒給結論當作 `applicable`。
- **建立待辦的時機改變**：5 號回傳事故類型後，平台要等到「至少一項保障是 `applicable`」才依範本建立待辦，並建立理賠申請書（D10）；都是 `excluded` 或 `insufficient` 時不建立。已建立的不會刪除。

**6 號**
- `Recognition.status` 多一種 `incomplete`（不合格）：`reason` 必填寫缺什麼；**`incomplete` 與 `failed` 不保留檔案**，`storage_path` 必須是空的。只有 `needs_review` 可以先存檔，使用者確認時沿用。
- `UploadedFile.target_todo_id`：使用者上傳時指定的待辦；有的話 `matched_todo_id` 只能是它或空。上傳 API 用選填的表單欄位 `todo_id` 接收（待辦不存在回 404）。
- `Recognition.stored_name`：6 號為檔案取的名字（事故類型_待辦名稱_序號.副檔名），資料庫的檔名也用它；沒給時平台用「文件代碼_序號.副檔名」。**資料庫不再存使用者上傳時的原檔名**。
- `TodoView` 加 `scope`、`document_code`、`requires_upload`、`keywords`、`notes`、`wait_note`、`without_document`；`ctx.todos` 現在包含同一張保單共用的行程待辦（`scope == "policy"`，理賠申請書 D10），`matched_todo_id` 可以指向它，`all_todos_done` 也包含它。
- `DocumentView.recognition_status` 多一種 `incomplete`；`DocumentView.confirmed_by_user`（使用者確認過這份「不確定」的文件，7 號的附件只取 `recognized` 或使用者確認過的）。
- `GoogleAccess.drive_folder_id(user)`：使用者 Drive 裡的理賠資料夾編號（授權時建立，沒建成會現場補建）；沒有 Drive 授權回 `None`。6 號用它，不要寫死資料夾名稱。`GoogleAccess` 的說明更正為 `drive.file`、`gmail.compose`（`gmail.send` 也對到 `gmail.compose` 的授權）。

**資料（維護者：Boris 與 5 號）**：`incident_catalog.json` 每個事故類型加 `coverage_keywords`（比對保單涵蓋的保障的章名；初始值待確認），以及事故類型層級的 `notices`（整個事故共用的提醒；初始預設值：保險期間，班機與行李類加「知悉事故後五日內通知」，其他類型寫不含天數的提醒；正式版本待確認）。

**API（第 3 步）**
- `POST /incidents/{id}/documents` 多一個選填的 `todo_id`（使用者在上傳時指定的那一項）。
- 新增 `POST /incidents/{id}/documents/{document_id}/confirm`（body：`todo_id`）：使用者確認一份「需人工確認」的文件，自己選要對到哪一項待辦；平台沿用 6 號先存的檔案，待辦由使用者完成（`done_by = user`）。非 `needs_review`、已確認過、沒有存檔、待辦不存在或不適用，各回 409／404。
- `PATCH /incidents/{id}/todos/{todo_id}`：**需上傳的待辦也能由使用者自己勾**（原本回 409），會標 `without_document`（規格 v3.4 的「未附文件」），取消勾選就清掉。契約流程測試與 e2e 改成讀 `requires_upload`，不再靠 `PATCH` 回 409 判斷。

**還沒做**：v2.1（7 號整張保單送件、Gmail 草稿、多封信）等 7 號輸入。

## 2026-11-05　契約 v2 第 1 步：資料表（提案見 [contract-v2-proposal.md](contract-v2-proposal.md)）

**契約檔案沒有改**；這一步只改資料表，契約型別與 context 組裝是下一步。
- `incident_document.incident_todo_id`：拿掉唯一限制，一項待辦可以收多份文件；改成一般索引。
- `incident_document.recognition_status`：多一種 `incomplete`（不合格）；檢查約束同步更新。
- `incident_document.confirmed_by_user`（新，預設 `false`）：使用者確認過這份「不確定」的文件。
- `incident_todo.without_document`（新，預設 `false`）：需上傳的待辦由使用者自行勾選、沒附文件。
- migration 的 downgrade 會把 `incomplete` 改回 `failed`，一項待辦有多份文件時只留最新的一份對應。
- 目前還沒有任何程式寫入或讀取新欄位與新狀態，所以行為不變。

## 2026-11-05　班機延誤文件清單（5、6 號對齊）

**契約檔案沒有改**；改的是理賠文件規則的資料（`incident_catalog.json`）與載入器。
- D01 標題改成「航空業者出具、載有班機延誤期間或取消的證明」（班機取消也共用 D01，新標題同時涵蓋）。
- D02 維持「機票及登機證，或航空業者出具的搭機證明」，需上傳（已在 2026-11-04 改好）。
- 班機延誤**不再列 D11**（存摺與護照影本）：條款沒有要求。D11 原本是「所有事故類型自動加上」，事故類型新增選填欄位 `exclude_documents`，列在裡面的文件代碼不套用。其他事故類型照舊有 D11，是否排除由文件規則維護者（Boris 與 6 號）另外決定。
- 載入器（`make seed`）重跑時，會刪掉資料檔不再列的舊範本；已用該範本建立的事件待辦保留，`todo_template_id` 變空。
- 班機延誤現在的清單是 D01、D02；理賠申請書（D10，整個行程一項）等契約 v2 由平台在第一次回傳事故類型時建立。
- 舊的開發資料庫要執行一次 `make seed`，班機延誤才會不再有 D11。

## 2026-11-04　依 5 號反饋對齊範例資料與假實作

**契約檔案沒有改**；改的是假實作、範例資料與契約測試。
- 事件類型代碼以 seed 為準：`flight_delay`、`flight_cancel`、`baggage_delay`、`baggage_loss`、`medical`、`document_loss`、`card_fraud`、`trip_cancel`（另有未判斷時用的 `other`）。舊範例的 `delay` 不再存在。
- `seed_sample_catalog` 改成載入 `make seed` 的同一份 `incident_catalog.json`，不再有另一份範例。
- `FakeIncidentAgent`：問完才回 `incident_type_code` 與待辦（v3.3）。建立事件後使用者第二次回答前 `finished=False`、不帶類型與待辦，之後才回類型並結束。建立事件當下事件沒有待辦（要等類型判斷出來）。
- 班機延誤文件對齊條款（富邦第 23 條等）：D02 改為「機票及登機證，或航空業者出具的搭機證明」且**需上傳**；D01 的注意事項註明要載明班機延誤期間。理賠申請書（D10）是整個行程一項，平台還沒建立（見下方「還沒實作」）。
- 契約測試：班機延誤現在有多項需上傳的待辦，整條流程測試改為「需上傳的上傳、其餘手動勾」。`TodoView` 還沒有 `requires_upload`／`document_code`，測試暫以 PATCH 回 409 判斷。
- 契約測試的問答改成「問到結束」（依 5 號建議）：第一句說明狀況，之後回「不知道」直到 `finished=True`，上限 15 輪；`finished` 之前不得有類型與該類型的待辦，之後類型要是 `flight_delay` 且待辦與出處都補上。真實的 5 號問幾題都能通過。

## 2026-11-04　依規格書 v3.3 調整理賠資料表

**契約（對 5、6、7 的實作）**
- `TodoView` 新增 `status`：`pending`／`done`／`not_applicable`。**`is_done` 保留**，等於 `status == "done"`，既有程式不用改。
- `IncidentContext.all_todos_done`：排除 `not_applicable` 的待辦；其餘都完成才算（沒有任何可算的待辦時仍為 False）。
- `PATCH /incidents/{id}/todos/{todo_id}`：`not_applicable` 的待辦與需上傳的待辦（`requires_upload`）不能手動勾選，回 409。
- 6 號文件辨識通過時，平台把對應待辦的 `status` 設為 `done`、`done_by="agent"`。「不適用」只有 5 能標。
- 契約檔案（`incident_agent.py`、`document_agent.py`、`package_agent.py`）本身沒有改。

**資料表（只讀，供理解 `IncidentContext` 的來源）**
- `incident_todo`：`is_done` → `status`；新增 `is_new`、`document_code`、`requires_upload`、`wait_note`、`notes`（注意事項，多條）、`policy_id`（整個行程共用的理賠申請書，`incident_id` 與 `policy_id` 二選一）。同事件內同一 `document_code` 只列一次。
- `incident_document.incident_todo_id` 唯一（一項待辦一份文件，重傳取代舊的）；新增 `size_bytes`、`storage_provider`。
- `incident_submission` → `policy_submission`（以保單為單位）：`status` 為 `pending`／`drafted`／`sent`／`self_submitted`，新增 `recipient`、`sent_at`、`gmail_refs`；`external_ref` 移除（寫進 `gmail_refs`）。
- `incident_clause`：新增 `conclusion`（`applicable`／`excluded`／`insufficient`）、`amount_note`。
- `incident_type`：新增 `item_keys`、`fields`（必問欄位）；`todo_template`：新增文件規則欄位（`document_code`、`notes`、`wait_note`、`requires_upload`、`major_*`、`keywords`、`condition`）。
- `policy`：新增 `destination`、`summary_at`、`last_step`、提醒信三欄、`closed_at`；`conversation` 新增 `is_draft`。
- `user.google_sub` 移除，登入身分在 `identity`；新增 `google_grant`。
- seed：`make seed` 載入 8 種事故類型與 D01~D23 文件規則（`backend/data/config/incident_catalog.json`）。

**還沒實作（契約之後可能再改）**：依 `todo_template.condition` 產生待辦、理賠申請書的建立與「新狀況」合併、提醒信排程、送件改以整張保單為單位（`ClaimPackager.build` 目前仍只拿單一事件）、6 號取得 Drive 資料夾的方式。

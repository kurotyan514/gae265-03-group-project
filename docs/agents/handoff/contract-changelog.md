# 介面契約變更紀錄

5、6、7 號 agent 的契約（`backend/app/contracts/`）、`IncidentContext` 與相關資料表的變更。**新的寫在最上面**。變更契約的人要在這裡加一筆，並更新對應的交接說明（`agent-5/6/7-*.md`）、契約測試與 `make client`。

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

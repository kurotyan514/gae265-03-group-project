# 介面契約變更紀錄

5、6、7 號 agent 的契約（`backend/app/contracts/`）、`IncidentContext` 與相關資料表的變更。**新的寫在最上面**。變更契約的人要在這裡加一筆，並更新對應的交接說明（`agent-5/6/7-*.md`）、契約測試與 `make client`。

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

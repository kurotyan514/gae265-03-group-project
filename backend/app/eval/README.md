# Agent 6 文件辨識評估

`make eval-documents` 用 repo 外的測試文件與答案比對辨識結果。照片或掃描檔可能送 Azure Document Intelligence；Drive 與 Google 授權一律使用假的，不驗證真實 Drive 整合。執行前先確認原圖傳送範圍與費用，並跑 `make doctor`。

資料集的 `answers.json` 是案例清單，不能直接放舊資料集的 `ground_truth/answers.json`。原始資料不改，另存轉換副本；不得用受測程式的輸出反推標準答案。

每筆案例可包含：

| 欄位 | 用途 |
| --- | --- |
| `file`、`code`、`expect` | 相對檔案路徑、通過時的文件代碼（6 號認得的代碼，見 `codes.SPECS`；或 null）、預期狀態或允許狀態清單（狀態以契約 `Recognition.status` 為準） |
| `todo_complete` | 預期待辦是否完成。單張機票或登機證應為 false；不提供時只驗基本安全條件，報告標示 `completion_checked=false` |
| `matched_todo_id` | 預期待辦 UUID；明寫 null 表示不得對應待辦，省略則依代碼檢查 |
| `fixture` | 案例事件檔的相對路徑，內容為 `ctx`（IncidentContext）與 `user`（UserContext），不包含答案。省略時用預設事件：6 號認得的每種文件各一項待辦，階段讀 `incident_catalog.json` |
| `group` | supported、unsupported、format、storage，分開計分；沒有案例的組別也會列出（分母 0） |
| `profile` | authorized_storage_success（預設）、no_google_access、storage_failure，全部使用假 Drive |
| `score`、`review_note` | 待釐清案例設 false 並填原因；不執行、不計分，但會列在報告，不能隱藏排除數量 |
| `personal` | 合成測試資料的個資值清單，檢查 reason 與 document_kind 是否外洩；不傳給受測 Agent |

事件檔要保留原情境，舊欄位到 v2 的對應需記錄在轉換說明。評估器不補日期／航班相符性等 Agent 尚未實作的能力。

執行方式：先由使用者設定 `.env` 的 `DOCUMENT_EVAL_DIR`，或用 `make eval-documents args="--dataset /完整資料集路徑"` 明確指定。含空白的路徑須在 args 內另加引號。

輸出 `report-模型-UTC時間.json`，每次建立新檔，不覆蓋先前基準。報告保留答案指紋、各組的分母／正確數／分數、未執行案例、實際待辦完成狀態與存檔驗證。總分只供參考，應以分組與覆蓋缺口解讀；未執行不能算通過。

零容忍項目：錯勾／錯對待辦、個資外洩、未存成功卻回通過、不應通過的文件被放行、failed／incomplete 或無授權卻保留檔案。任一發生，CLI 回非零退出碼。回覆有個資時只記警示，不將原文複製進報告。

資料集、原始與轉換答案、逐案報告不加入 repo。只將通用評估程式與假服務測試放進 repo。

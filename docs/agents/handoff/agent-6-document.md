# 6 號 agent：文件辨識

契約：`backend/app/contracts/document_agent.py`（`DocumentRecognizer`、`Recognition`、`UploadedFile`）　假實作：`FakeDocumentRecognizer`
畫面：2-8 上傳文件。先讀 [README.md](README.md)。對應 issue #36。

## 你的工作

使用者照事件待辦做事後，把收據、證明等文件拍照或上傳。你要：

1. 辨識這是哪一種文件，對應到事件的哪一個待辦。
2. 檢查文件是否合格（內容清楚、類型正確）；不合格要說明原因，讓使用者補件。
3. 把確認無誤的文件**存到使用者自己的雲端**（Google Drive），回傳存放位置。
4. 告訴平台這個待辦可以勾起來了。

## 介面

```python
class DocumentRecognizer(Protocol):
    async def recognize(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition: ...
```

### 你拿到的

- `ctx.todos`：這個事件的待辦（含 `id`、`title`、`phase`、`status`、`is_done`；`not_applicable` 的待辦不要對應），辨識結果要對應到其中一個。
- `ctx.facts`、`ctx.policy`：可用來判斷文件是否相符（例如日期是否在保險期間內）。
- `file`：`file_name`、`content_type`、`content`（bytes，上限 10 MB）。
- `google.access_token(user, scope)`：取得使用者授權的 Google token（存雲端需要 `drive.file`）。**目前平台還沒有保管授權，一律回傳 None**。

### 你交出的

`Recognition`：

| 欄位 | 說明 |
| --- | --- |
| `status` | `recognized`（辨識通過）／`needs_review`（需人工確認）／`failed`（失敗） |
| `document_kind` | 辨識出的文件類型（例如「診斷書」「費用收據」） |
| `matched_todo_id` | 對應的待辦 id，必須在 `ctx.todos` 內；對應不到就是 None |
| `todo_complete` | 文件確認無誤、待辦可以勾起來。只能在 `recognized` 且有 `matched_todo_id` 時為 True |
| `storage_path` | 已存到雲端的位置；`recognized` 一定要有 |
| `confidence` | 0～1，可空 |
| `reason` | 需人工確認或失敗的原因，也當作補件提醒；**不可含文件內容或個資** |
| `failure` | `failed` 時是哪一種（v2.9）：`unreadable` 讀不出來（畫面「無法辨識」）／`not_matched` 不在這個行程的待辦裡（畫面「辨識失敗」） |
| `found_fields` | 合格規範裡在文件上找到的欄位名稱，例如「延誤期間」（v2.9）；只有名稱，不含內容 |

### 選配：確認後改檔名（契約 v2.2，#160）

使用者確認一份「不確定」的文件、對上待辦後，平台會呼叫你的 `rename_confirmed`（`DocumentRenamer`，沒實作就略過）：把 Drive 上的「待確認」檔案改成「事故類型_待辦名稱_序號」，回傳新檔名，平台把資料庫的檔名也改成它。改不了回 `None`，確認照常完成。送件信的附件檔名是寄信時從 Drive 讀的，所以 Drive 一定要一起改。

### 選配：選完待辦再檢查、刪掉暫存檔（契約 v2.11，規格 v3.7 第 3 點）

- `recheck`（`DocumentRechecker`）：使用者替「需要你確認」的文件選了待辦後呼叫。讀回先存的檔案，當成那項待辦的文件檢查；合格回 recognized，不合格或讀不出來先刪掉雲端的檔案再回 incomplete／failed，暫時做不到回 needs_review。
- `discard`（`DocumentDiscarder`）：使用者選「都不是」、或上次沒選就離開時呼叫，永久刪除暫存檔；刪不掉回 False。

## 規則（違反會被平台擋下，回 502）

1. `matched_todo_id` 屬於這個事件。
2. `recognized` 一定有 `storage_path`；沒存成功就不能是 recognized。
3. `todo_complete` 只能出現在 `recognized` 且有 `matched_todo_id` 的結果。
4. 沒有 Google 授權（token 是 None）：回 `needs_review`，`reason` 寫「請使用者先授權存取雲端」，**不要丟例外**。
5. 文件內容與辨識結果可能含個資：log 與 `reason` 不放內容；文字送進 LLM 前先去識別化（`backend/app/policy/deidentify.py`）。
6. 文件類型與待辦怎麼對應由程式規則決定（可用 LLM 輔助判斷類型，但對應與勾選由程式），比照 ADR-0004、0011。

## 待你和使用者決定的事（#36）

- 原檔存雲端與 ADR-0009「伺服器不保存原檔」要一起寫進決定：伺服器只留 `storage_path`。
- OCR 用什麼（雲端文件辨識、本機 Tesseract、具視覺能力的 LLM），個資是否先去識別化；現有的 `TextExtractor` 介面見 [ADR-0012](../../adr/0012-text-extractor-and-ocr-module.md)。
- 資料表已有 `incident_document.recognition_status`、`document_kind`、`recognition_reason`；若還需要欄位，請提出來由平台負責人調整 schema。

## 驗收

- `CONTRACT_AGENT_6=<你的註冊名稱> make test args="-k contracts"` 全過。
- 自己補的測試：各種文件各一份的辨識結果、合格與不合格各一、沒有授權時的行為、log 不含內容。

## 給你的 AI 助手

> 請依 `docs/agents/handoff/README.md` 的規則，實作 `DocumentRecognizer`（見 `backend/app/contracts/document_agent.py`）。先讀 `FakeDocumentRecognizer`，再寫測試。存雲端、OCR、LLM 都包成可注入的函式，測試用假的且不連網；沒有 Google 授權時回 needs_review 不丟例外；log 與 reason 不放文件內容。實作放 `backend/app/agents/document/`，並在 `app/agents/registry.py` 用 `register_document_recognizer` 註冊。

## 合格規範的決定（2026-11-10，Lala 與 Leon，規格 v3.7）

- 延誤證明只要求載明延誤期間（原定與實際起飛時間，或延誤時數）；班機取消則載明取消。延誤原因不是必要條件，缺了照樣通過、只提醒（安達、富邦公開的理賠文件要求也只寫延誤期間）。
- 理賠文件規則的注意事項全部是必要條件，缺了就不合格；規則以外的提醒由 6 號的規則檔用固定句子產生，不用 LLM。
- 不合格時，下一步由程式套公式組句：「請向〈開立單位〉索取載明〈缺少項目〉的〈文件名稱〉」，規則檔每條多一個 `issuer`（開立單位）。
- 看得出是理賠文件、但不確定是哪一份時，6 號交出候選待辦（`candidate_todo_ids`），畫面只列這幾項，另外有「看全部」與「都不是」。
- 存檔順序維持「先審再存」：通過才歸檔、要確認的先存成「待確認」、不合格與辨識失敗不存。
- 手寫文件暫緩處理。

## 海外就醫文件（2026-11-13，Lala，#233 泰國醫療 demo）

- 6 號多認四種文件：D13 診斷書、D14 醫療費用收據、D24 受益人身分證明、D25 保險單。demo 情境是在泰國吃壞肚子得了急性腸胃炎、看門診不住院，範例文件是虛構的曼谷診所開的泰英雙語診斷書與收據，加上旅客自己的台灣護照、身分證影本，電子保單與安達申請書（`samples/med_*.pdf`）。
- 受益人身分證明（D24）認「國民身分證」「居留證」，護照則看資料頁最下面的機讀碼（`P<TWN…`）。不用「passport」當關鍵字，因為診斷書、收據上也常印「Passport No.」。D24 沒有合格規範，認得出種類就通過。
- 就診日期（D13）與收據日期（D14）讀得出來時，要落在保單的保險期間內（`within_policy_period`，日期由 `dates.py` 讀，支援西元、日／月／年與月／日／年、英文月份、泰國佛曆與月份縮寫、民國年；分不出日月順序時兩種讀法有一種在期間內就算）。不在期間內回「需要你確認」，不寫出日期本身；使用者確認後重新檢查會放行。讀不出日期就只檢查有沒有寫。
- 國外單據多半是英文，去識別化另外遮英文的病患姓名、護照號碼、病歷號（HN）與護照機讀碼。
- 保險單（D25「保險單或其謄本」，Boris 於 catalog 新增）認「保險單」「電子保單」「投保證明」「policy schedule」等；「保單」不當關鍵字，因為申請書上有「保單號碼」欄。
- 醫療 demo 的申請書用安達官網公開的「保險金申請書」（Form004 第 1 頁，`samples/chubb_claim_form_blank.pdf`），手寫填醫療事故（`samples/claim_medical.py`）。電子保單用組員提供的安達網路投保保單第 3 頁當底稿：`samples/chubb_policy_blank.pdf` 已把原本的姓名、保單號碼、保險期間等個資整段移除，再由 `make_samples` 填上虛構資料。證件影本是虛構的文字版面，不畫國徽、底紋、照片等防偽設計。
- 條款的理賠文件條只列「醫療診斷書或住院證明」「醫療費用收據」，沒有逐欄規定；欄位依給付條件推出（條號以安達 CHUBB04 為例，臺產 TFMI08、華南 HUANAN07、泰安 TAIAN03、富邦 FUBON02 寫法相同）：
  - 保險範圍（CHUBB04 第 4 條）：「本契約有效期間內，在海外因第二條定義之突發疾病住院、門診或急診診療」，所以要看得到病名（判斷是不是突發疾病、有沒有不保事項）與就診日期（判斷在不在保險期間內）。
  - 門診醫療保險金（CHUBB04 第 6 條）：「就其實際發生之門診醫療費用給付」，所以收據要看得到金額。
  - 理賠文件條（CHUBB04 第 13 條、FUBON02 第 12 條）：外幣收據「以收據開立日為匯率計算日」，所以收據要看得到日期。
- 診斷書（D13）照理賠文件規則的注意事項，病名與就診日期都是必要條件。
- 醫療費用收據（D14）要看得到金額與日期，缺了就不合格：醫療是實支實付，金額是理賠的依據；日期是外幣換算的匯率計算日，也用來核對是否在保險期間內。
- 「收據」「receipt」很常見（機票行程表、便利商店、飯店都有），同一份文件也看得到醫療字眼（醫院、診所、門診、medical、clinic…）時才當成醫療費用收據。

## 契約 v2.13：行程版（選配，ADR-0029）

行程頁只有一個上傳框，平台之後會改呼叫 `recognize_trip`、`recheck_trip`、`discard_trip`、`rename_trip`（`app/contracts/document_agent.py` 的 `TripDocument*` 協定），收 `TripContext`（`for_agents_6_7()` 後的）。規則與舊方法相同，另外：待辦在整個行程（共同文件加各事件）裡找；同一文件代碼對到多個事件時回 `needs_review` 加 `candidate_todo_ids`，不自己挑事件；共同文件（`todo.incident_id` 是 `None`）檔名「共同文件_待辦名稱_序號」。沒實作時平台退回逐事件的舊方法。假實作可當範例。完整說明見 contract-changelog 的 2.13.0。

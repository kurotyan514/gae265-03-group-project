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

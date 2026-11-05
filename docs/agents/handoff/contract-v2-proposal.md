# 契約 v2 提案

給 5、6、7 號的開發者與你們的 AI 助手。**這是提案，還沒實作**；三位確認後才動手。變更紀錄在 [contract-changelog.md](contract-changelog.md)，目前的契約在 `backend/app/contracts/`。

- 日期：2026-11-05（依據：agent6 開會對齊事項、5 號與登入負責人的意見、規格書 v3.4、ADR-0021、PR #86 的實際程式）
- 原則：**只新增，保留舊欄位**。新欄位都有預設值，新的選項是「多一種值」，不改既有欄位的意思；用 v1 寫的實作不改也能跑。
- 版本：契約加 `CONTRACT_VERSION`（v2.0 是 `"2.0.0"`），變更紀錄、契約測試與交接說明都對這個版本。
- 分兩批：**v2.0** 是 5、6 號這週的 prototype 會用到的；**v2.1** 是 7 號的整張保單送件，要等 7 號輸入。

## 1. 總表

| # | 變更 | 契約檔 | 資料表／API | 誰受影響 | 來源 |
| --- | --- | --- | --- | --- | --- |
| 1 | 一項待辦可收多份文件，何時完成由 6 號回報 | 無（說明寫清楚） | 拿掉 `incident_document.incident_todo_id` 的唯一限制 | 6、7 | B1、L1 |
| 2 | `TodoView` 加文件代碼等欄位 | `TodoView` | 無 | 5、6、7 | B3 |
| 3 | 辨識結果加第四種「不合格」`incomplete` | `Recognition`、`DocumentView` | 辨識狀態的檢查約束加一個值 | 6 | agent6 #1 |
| 4 | 上傳時指定待辦 | `UploadedFile` | 上傳端點加選填的 `todo_id` | 6 | agent6 #2 |
| 5 | 理賠申請書（D10）進 `ctx.todos` | `TodoView` | 建立時機、驗證放寬 | 5、6 | agent6 #3、#71 |
| 6 | 「不確定」與「不合格」可以先存檔 | 契約說明 | 使用者確認的 API | 6、7 | agent6 #4、B5 |
| 7 | 檔名：一個沒有個資的名字，DB 與 Drive 共用 | `Recognition` | 不存原檔名 | 6、7 | agent6 #5、B6 |
| 8 | 理賠資料夾經 `GoogleAccess` 給 6 號 | `GoogleAccess` | 無（資料夾由 PR #86 的授權流程建立） | 6 | agent6 #7、B7 |
| 9 | 事故類型清單與必問欄位進 context | `IncidentContext` | 無 | 5 | 5 號 |
| 10 | 條文結論與額度說明 | `ClauseUpdate`、`ClauseView` | 無（資料表已有） | 5 | 5 號 |
| 11 | 重大注意事項由平台算好放進 context | `IncidentContext` | 無 | 5 | 5 號、決議 |
| 12 | 需上傳的待辦也能自行勾選，標「未附文件」 | `TodoView` | `PATCH` 放寬、待辦加欄位 | 全部 | 規格 v3.4 |
| 13 | 契約測試改用假授權、假存檔，加「沒授權」劇本 | 無 | 測試 | 6、7 | B4、S4 |

7 號的整張保單送件、Gmail 草稿等見第 6 節（v2.1）。

## 2. 對 agent6 提出的 7 項的評估

| agent6 的提議 | 評估 | 做法 |
| --- | --- | --- |
| 1. 加第四種結果「不合格」 | **採用** | `Recognition.status` 加 `incomplete`：文件是對的種類，但不符合規定（缺頁、缺欄位），`reason` 寫缺什麼。與 `failed`（讀不出來、不是這類文件，請重新上傳）和 `needs_review`（不確定，可由使用者確認）區分。v2 之前 6 號先回 `failed` 並在 `reason` 寫缺什麼 |
| 2. 在指定的待辦上上傳 | **採用，放在 `UploadedFile`** | 加選填 `target_todo_id`。放在 `UploadedFile` 而不是 `recognize` 的參數，v1 的實作不用改簽名。和 B5（上傳後才選）不同，兩者都要 |
| 3. D10 要在待辦清單裡 | **採用，平台做** | `ctx.todos` 帶入同一張保單的行程待辦；`matched_todo_id` 可指向它。見第 3 節 |
| 4. 「不確定」時先存檔 | **採用，寫進契約** | `needs_review` 與 `incomplete` 可帶 `storage_path`，平台照存；使用者確認（B5）時直接用這份，不用重傳。目前程式沒禁止，這次寫明 |
| 5. 檔名對齊規格書 | **調整** | 規格書的名字（`事故類型_待辦名稱_序號`）沒有個資，所以 DB 與 Drive **共用同一個名字**，由 6 號命名，用 `Recognition.stored_name` 回傳；不需要另存 `D01_1.jpg`。6 號沒回（v1 實作）時，平台才用 `{文件代碼}_{序號}.{副檔名}` 補 |
| 6. 完成條件由 6 號回報 | **採用，不改契約** | `todo_complete` 的意思是「加上這份，這項待辦要求的文件都齊了」；6 號看得到 `ctx.documents` 裡這項待辦已有的文件。D02 要不要兩份，等 Leon 在規格書確認 |
| 7. 理賠資料夾由誰建 | **已有人建，契約補一個取得方式** | PR #86（Carol）在使用者**第一次授權 Drive** 時建立資料夾並存進 `google_grant.drive_folder_id`。契約加 `GoogleAccess.drive_folder_id(user)` 給 6 號取得，由平台在 #86 合併後實作。見第 4 節 |

另外一個要更正的地方：`GoogleAccess` 的說明寫「gmail.send」，ADR-0020 決定的是 **`gmail.compose`**，v2 把說明改成 `drive.file`、`gmail.compose`。PR #86 的實作兩種寫法（短名或完整網址）都收，`gmail.send` 也對到 `gmail.compose` 的授權，所以 7 號的程式不用改。

## 3. v2.0 的契約型別

只列變動的部分。所有新欄位都有預設值。

```python
CONTRACT_VERSION = "2.0.0"

class TodoView(BaseModel):  # 既有欄位不動，新增：
    scope: Literal["incident", "policy"] = "incident"  # policy：整個行程共用（D10）
    document_code: str | None = None      # 例如 "D01"，6 號用它對待辦，不用猜標題
    requires_upload: bool = False
    keywords: list[str] = []
    notes: list[str] = []
    wait_note: str | None = None
    without_document: bool = False        # 使用者自行勾選、沒附文件（規格 v3.4）

class UploadedFile(BaseModel):  # 新增：
    target_todo_id: uuid.UUID | None = None   # 使用者在 2-3 指定的那一項；沒有就由 6 號判斷

class Recognition(BaseModel):
    status: Literal["recognized", "needs_review", "incomplete", "failed"]  # 新增 incomplete
    stored_name: str | None = None        # 6 號為存到 Drive 的檔案取的名字

class DocumentView(BaseModel):
    recognition_status: Literal["pending", "recognized", "needs_review", "incomplete", "failed"]

class GoogleAccess(Protocol):
    async def access_token(self, user: UserContext, scope: str) -> str | None: ...
    async def drive_folder_id(self, user: UserContext) -> str | None: ...  # 新增

class FieldView(BaseModel):             # 事故類型的必問欄位
    key: str
    name: str
    type: str                           # date／time／place／select／bool／desc，值見資料檔
    options: list[str] = []
    question: str

class EventTypeView(BaseModel):
    code: str
    name: str
    fields: list[FieldView]

class IncidentContext(BaseModel):       # 新增：
    event_types: list[EventTypeView] = []   # 全部事故類型
    common_fields: list[FieldView] = []     # 每個類型共用的必問欄位（日期、地點）
    major_notices: list[str] = []           # 重大注意事項，最多 4 條，平台算好

class ClauseView(BaseModel):            # ClauseUpdate 同樣加：
    conclusion: Literal["applicable", "excluded", "insufficient"] | None = None
    amount_note: str | None = None
```

### 規則（平台會驗證，違反回 502）

- `Recognition.status == "incomplete"` 一定要有 `reason`，寫缺什麼；不可含文件內容或個資。`todo_complete` 必須是 `False`。
- `needs_review`、`incomplete` 可以有 `storage_path`；`recognized` 一定要有（原本的規則不變）。
- 上傳有 `target_todo_id` 時，`matched_todo_id` 只能是它或空；文件不符合那一項要的東西，回 `incomplete`（或 `failed`），不要自己改配到別的待辦。
- `matched_todo_id` 可以指向 `scope == "policy"` 的待辦（同一張保單）。
- `stored_name` 命名：`{事故類型名稱}_{待辦名稱}_{序號}.{副檔名}`，序號是這項待辦已有的文件數加一；不可含使用者上傳的原檔名。
- 沒有授權時：6 號回 `needs_review` 並說明「請先授權 Drive」，7 號回 `failed`；`access_token` 與 `drive_folder_id` 回 `None`（ADR-0020：授權分段，登入時不要求）。

## 4. 平台要做的事

**資料表（需要 migration）**
- `incident_document`：拿掉 `incident_todo_id` 的唯一限制；辨識狀態的檢查約束加 `incomplete`；加 `confirmed_by_user`（使用者確認過的「不確定」文件）。
- `incident_todo`：加 `without_document`。

**API**
- 上傳端點加選填 `todo_id`。
- 新增「使用者確認」端點（B5）：使用者選待辦後，平台把文件對到待辦並標完成（`done_by = user`）。7 號的附件只取 `recognized` 或使用者確認過的文件。
- `PATCH` 待辦：放寬需上傳的待辦（原本回 409），標 `without_document`。
- `incident_document.file_name` 不再存使用者的原檔名（B6），改存 `stored_name`。

**組裝 context**
- `ctx.todos` 帶同一張保單的行程待辦（D10）；`apply_recognition` 允許指向它；`all_todos_done` 包含它。
- 帶 `event_types`、`common_fields`、`major_notices`（`todo_template.major_*` 依優先序取前 4 條）。
- 理賠申請書（D10，整個行程一項）由平台在 5 號**第一次回傳事故類型**時建立，5 號不用 `TodoProposal` 補。

**授權（依據 PR #86 的實際程式，要等它合併後才能做）**
- #86 的 `GrantGoogleAccess.access_token` 已經照契約運作：有效且含要求的 scope 才回 token，其餘（沒授權、已取消、失效、缺 scope、Google 暫時連不上）都回 `None`，不丟例外。契約這邊不用改。
- 在 `GrantGoogleAccess` 加 `drive_folder_id`，讀 `google_grant.drive_folder_id`。沒有 Drive 授權回 `None`。
- **補洞**：#86 在建資料夾失敗時，授權照樣存下來，資料夾編號會是空的，要等使用者下次重新授權 Drive 才會再建。所以 `drive_folder_id` 在「授權有效但沒有資料夾」時，要用換發的 token 現場補建並存起來，不要讓 6 號卡住。
- **資料夾名稱**：#86 實際建的是「好險有你 理賠文件」，ADR-0021（PR #84）寫的是「旅遊保險理賠」。以 #86 的程式為準，6 號不要寫死名稱，一律用 `drive_folder_id`；請 6 號把 ADR-0021 的名稱更正。
- 資料夾被使用者在 Drive 刪掉時，6 號回 `needs_review` 並提示重新授權；自動重建之後再補。
- Testing 狀態下授權約 7 天失效是正常流程（ADR-0020）：6 號回 `needs_review`、7 號回 `failed`，`reason` 寫「請先授權」，前端顯示重新授權按鈕。

## 5. 契約測試怎麼改

- 整條流程用假授權、假存檔；另加「沒授權」劇本（6 號回 `needs_review`、7 號回 `failed`）。#86 合併後，沒設定 Google 的環境（包含自動測試）`get_google_access()` 仍回「一律 `None`」的版本，所以契約測試不受影響，假授權要自己提供，也要有 `drive_folder_id`。
- 判斷待辦要不要上傳改讀 `requires_upload`，不再靠 `PATCH` 回 409。
- 新增案例：同一項待辦上傳兩份、`incomplete`、指定待辦上傳、D10 辨識、`needs_review` 帶 `storage_path` 再由使用者確認。
- 假實作（`Fake*`）跟著支援以上情境，讓還沒有真實實作的人也跑得起來。
- 契約測試先對版本：`CONTRACT_VERSION` 與變更紀錄的最新一筆對得上。

## 6. v2.1：7 號（待 7 號確認）

這幾項是從規格與計畫整理的缺口，**還需要 7 號的輸入再定案**：

- `ClaimPackager.build` 目前只拿單一事件，規格要整張保單。提議：新增 `build_for_policy(policy_ctx)`，平台優先呼叫；沒實作的 v1 實作維持用 `build`，每個事件各一次。
- `AttachmentRef` 缺檔案大小（`incident_document.size_bytes` 已有），7 號要用它把附件分到幾封信。
- `SendResult.status` 加 `drafted`（Gmail 草稿），並能回多個信件編號（一次送件拆成多封信）。
- 取檔：7 號自己用 `storage_path`（Drive 檔案編號）和 `drive.file` 授權向 Drive 取檔，**不經過 6 號**（ADR-0021）。
- 附件檔名：用 `stored_name`，與規格書的「加序號」一致。

## 7. 實作順序

1. 這份提案三位確認。
2. **PR 1** migration 與模型（唯一限制、`incomplete`、`confirmed_by_user`、`without_document`）。
3. **PR 2** 契約型別、`CONTRACT_VERSION`、context 組裝、驗證放寬、假實作、契約測試、變更紀錄。
4. **PR 3** API（指定待辦、使用者確認、`PATCH` 放寬、D10 建立）。
5. v2.1 等 7 號輸入後另案。

## 8. 還沒定案的問題

1. D10 的建立時機：5 號第一次回傳類型時建立，如果事件一直停在「其他」類型就不會建立。這樣可以嗎？（已與 5 號談過，採「第一次回傳類型」。）
2. `all_todos_done` 包含 D10 後，同一張保單有多個事件時，D10 沒完成會讓每個事件都不能送件。Demo 只有單一事故，先接受；多事件的語意等 7 號的整張保單送件一起定。
3. 使用者確認過的「不確定」文件要不要在畫面上標示。規格書沒寫，已請 Leon 補。
4. D02（機票與登機證）要不要兩份才算完成，等規格書確認。
5. 授權過期（Testing 狀態約 7 天）時，6 號與 7 號的提示文字，沿用 ADR-0020 的說法。
6. 上傳畫面在選檔之前會先確認 Drive 授權（#86 的前端）。新增的「指定待辦上傳」與「使用者確認」介面要接進同一個畫面，需要和 Carol 協調，避免兩邊同時改開發用的事件頁。

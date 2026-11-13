# 介面契約變更紀錄

5、6、7 號 agent 的契約（`backend/app/contracts/`）、`IncidentContext` 與相關資料表的變更。**新的寫在最上面**。變更契約的人要在這裡加一筆，並更新對應的交接說明（`agent-5/6/7-*.md`）、契約測試與 `make client`。

## 2026-11-13　契約不變（仍是 2.12.0）：醫療類加 D25「準備保險單或電子保單」（#233）

**契約檔案沒有改**；改的是 `incident_catalog.json`。
- **為什麼**：安達、臺灣、華南、泰安的海外突發疾病醫療與傷害醫療理賠文件條都要「保險單或其謄本」（例如 CHUBB04 第 13 條、TFMI08 第 14 條），原本沒有列成待辦，送件時會少這一份。富邦的醫療條款沒要求，catalog 還不分保險公司，所以醫療類一律列。
- **新增 D25「準備保險單或電子保單」**，只加在醫療類（`injmed`、`illmed`），`after_return`，沒有條件。notes：網路投保收到的電子保單或投保證明也可以。
- 6 號認得電子保單（關鍵字「保險單」「電子保單」「投保證明」等；申請書上也有「保單號碼」欄，所以「保單」不當 6 號的關鍵字）。
- 待決：是否改成平台直接附上使用者已上傳的保單 PDF、不用再傳一次（分工表 MED-02）。
- 拉到要 `make seed`，舊事件的待辦不會自動補。

## 2026-11-12　契約 v2.12.0：寄出與建立草稿後給 Gmail 連結、理賠頁顯示怎麼結案的（選配）

**版本號**：`CONTRACT_VERSION = "2.12.0"`。**只新增、選配**：5、6 號不受影響；沒給連結與信件編號的 7 號實作照樣能跑。
- **為什麼**：送件頁寄出或建立草稿後，使用者不知道信在 Gmail 的哪裡；回到理賠頁也看不出當初選了寄出、建草稿還是自己處理。
- `SendResult.gmail_url: str | None = None`：寄出時連到寄件備份的那封信（`#sent/<信件編號>`），建立草稿時連到那份草稿（`#drafts?compose=<草稿裡的信件編號>`）；用 `authuser=<寄件者 email>` 開在寄件的帳號。網址規則在 `app/domain/incident/gmail_link.py`，7 號與平台共用。
- `SendResult.message_id: str | None = None`：Gmail 信件編號。寄出時和 `external_ref` 相同；建立草稿時是草稿裡那封信的編號（`external_ref` 照舊是草稿編號）。平台存進 `policy_submission.gmail_refs`，之後在理賠頁重新組連結。
- 7 號正式版：
  - 轉接器的 `GoogleApi.create_draft` 改回 `GmailDraft(id, message_id)`（Gmail 網頁打不開草稿編號）。自己實作 `GoogleApi` 的人要跟著改。
  - 送件包沒有附件時，寄出與建立草稿只要 Gmail 授權，不再要 Drive（使用者可能沒上傳文件、也沒授權 Drive）。
- 平台：
  - `policy_submission` 多 `incident_id`（可為空，加這欄之前的紀錄是空的）；草稿的 `gmail_refs` 多存 `message_id`。**要 migration**。
  - `POST /incidents/{id}/submission` 的回應多 `subject`（填好空格的主旨）與 `gmail_url`；連結不是 `https://mail.google.com/` 開頭的不帶出。
  - `POST /incidents/{id}/submission` 檢查「被保險人姓名」「聯絡電話」的格式，不對回 422（規則在 `app/domain/incident/fill_rules.py`，前端 `fillRules.ts` 同一套）。
  - 新 API `GET /incidents/{id}/submission`：這個事件怎麼結案的（`sent`／`drafted`／`self_submitted`，還沒結案是 `null`）與 Gmail 連結。
  - 新 API `GET /incidents/{id}/drive-folder`：Google Drive 上這次的行程資料夾網址（只找不建，找不到給理賠資料夾，沒有 Drive 授權回 `null`）。
- 前端：
  - 送件頁寄出或建立草稿成功後跳出視窗，顯示主旨，「到 Gmail 查看寄件備份／草稿」按鈕打開那封信，另有「關閉」。
  - 理賠頁送件區依結案方式換說明；「到 Gmail 查看」打開那封信或草稿（自己處理的不顯示），「下載全部文件」打開 Drive 行程資料夾。
  - 送件頁沒上傳過文件時只問 Gmail 授權；Gmail 授權說明依建立草稿或寄出換文字。
- 拉到要 `make migrate`、`make client`。

## 2026-11-10　契約 v2.11.0：選完待辦再檢查一次、刪掉沒選的暫存檔（選配，規格 v3.7 第 3 點）

**版本號**：`CONTRACT_VERSION = "2.11.0"`。**只新增、選配**：5、7 號的程式不用改；沒實作新介面的 6 號照舊能跑（平台退回原本的「使用者確認」）。
- `DocumentRechecker.recheck(ctx, document, todo, user, google) -> Recognition`：使用者替「需要你確認」的文件選了待辦，6 號讀回先存的檔案，當成那項待辦的文件檢查合格規範。合格回 recognized（沿用 storage_path、可改名，`todo_complete` 照完成條件）；不合格、讀不出來時 **6 號先刪掉雲端的檔案**，回 incomplete／failed（storage_path 空的）；暫時做不到回 needs_review。
- `DocumentDiscarder.discard(ctx, document, user, google) -> bool`：刪掉還沒確認的暫存檔（永久刪除，不放垃圾桶）。
- `DriveStorage` 協定多 `download`、`delete`；自己實作 DriveStorage 的人要補。
- 新 API：
  - `POST /incidents/{id}/documents/{document_id}/recheck`（`{todo_id}`）：回應和上傳一樣（`DocumentOut`）。合格才對上待辦，達到完成條件時由 6 號勾起（`done_by = agent`）；不合格或讀不出來時文件紀錄拿掉。平台檢查：沒通過卻帶 storage_path、或 matched_todo_id 不是使用者選的 → 502，一筆都不寫。
  - `POST /incidents/{id}/documents/{document_id}/reject`：選「都不是」，當成辨識失敗，刪掉雲端的檔案與紀錄。
  - `POST /incidents/{id}/documents/discard-pending`（`{before}`）：打開行程（2-3、2-4）時清掉 `before` 以前上傳、還沒選的「需要你確認」文件，這次打開後才上傳的不動。
- 前端：處理清單的「需要你確認」那一列直接選待辦（只列候選、「看全部」、「都不是」），等選的時候上傳按鈕鎖住；2-4 辨識結果卡的確認也改成重新檢查。原本的 `confirm` 端點保留。
- 不需要 migration。拉到要 `make client`。

## 2026-11-10　契約 v2.10.0：不合格的缺少項目與下一步、需要你確認的候選待辦（選配，規格 v3.7）

**版本號**：`CONTRACT_VERSION = "2.10.0"`。**只新增、選配**：5、7 號的程式不用改。Lala 與 Leon 11/10 討論後的決定（見 `agent-6-document.md` 最後一節）。
- `Recognition.missing: list[str]`：不合格（`incomplete`）時缺了哪些欄位，畫面顯示「不合格：缺少〇〇」。
- `Recognition.next_step: str | None`：不合格時的下一步，由程式套公式「請向〈開立單位〉索取載明〈缺少項目〉的〈文件名稱〉」組成；6 號的合格規範每條多一個 `issuer`（開立單位）。
- `Recognition.candidate_todo_ids: list[UUID]`：需要你確認（`needs_review`）時 6 號認為可能的待辦，畫面只列這幾項，另外有「看全部」與「都不是」。**平台檢查必須是這個事件（或這張保單）的待辦**，不是就整筆拒絕（502）。
- 上傳回應（`DocumentOut`）帶出這三個欄位；目前不存資料庫。
- 理賠文件規則 D01 的注意事項改成「需載明班機延誤期間（原定與實際起飛時間，或延誤時數）；班機取消則載明取消」，拿掉「及原因」；延誤原因只提醒。拉到要 `make seed`、`make client`。

## 2026-11-09　契約 v2.9.0：6 號的「辨識失敗」與判斷依據（選配，規格 v3.7）

**版本號**：`CONTRACT_VERSION = "2.9.0"`。**只新增、選配**：5、7 號的程式不用改；平台與前端不接也照常運作。
- `Recognition` 新增 `failure: "unreadable" | "not_matched" | None`：`status = "failed"` 時是哪一種。`unreadable` 是讀不出來（模糊、檔案打不開、有密碼），原型叫「無法辨識」，要重拍重傳；`not_matched` 是讀得出來但不在這個行程的待辦裡（風景照、收據、行李延誤證明傳到班機延誤），原型叫「辨識失敗」。兩種都不留檔。
- `Recognition` 新增 `found_fields: list[str]`：合格規範裡在文件上找到的**欄位名稱**（例如「延誤期間」「延誤原因」），給畫面顯示「辨識到：…」。只有名稱，不含文件內容。這種文件沒有合格規範時是空的。
- **6 號行為改變（規格 v3.7「使用者不需另外選待辦」）**：看不出是哪種理賠文件、或認得種類但這個行程沒有它的待辦，從「不確定（needs_review，先存檔、請使用者選待辦）」改成「`failed` + `not_matched`，不留檔」。以下仍然是「不確定」：使用者上傳時指定了待辦、文件像好幾種、對到好幾項待辦、只有 LLM 猜得出種類、照片沒有 Azure、沒有 Google 授權、存檔失敗、欄位是手寫。
- 給平台：`failure`、`found_fields` 目前**沒有存進 `incident_document`，API 也沒帶出**。要讓 2-3i 顯示「無法辨識／辨識失敗」與判斷依據，需要加欄位（migration）並放進 `DocumentOut`，之後 `make client`。
- 給前端：`DocumentsPage` 目前把所有 `failed` 都寫「辨識失敗」；平台帶出 `failure` 後，`unreadable` 要改顯示「無法辨識」。
- `/dev/document` 測試台的結果文字已改用原型說法：不通過分成「無法辨識」「辨識失敗」。
## 2026-11-09　契約 v2.8.0：預覽時確認附件還在不在 Drive（選配，#155 驗收 7-2）

**版本號**：`CONTRACT_VERSION = "2.8.0"`。**只新增、選配**：5、6 號不受影響；只收 `ctx` 的 7 號實作照樣能跑。
- **為什麼**：使用者在 Google Drive 刪除理賠文件後，系統裡的文件紀錄還在，預覽信照樣列為附件，寄出時才失敗；重新上傳只會多一份，舊的那份仍被當成附件，事件寄不出去。平台沒有刪除文件的功能。
- `ClaimPackager.build(ctx, google=None, user=None)`：多兩個選填參數。平台的預覽（`GET /incidents/{id}/package`）與送件（`POST /incidents/{id}/submission`）都帶上目前使用者與 `get_google_access()`；**只對簽名有 `google`、`user` 的實作帶**，舊實作照舊只給 `ctx`。送件時用同樣的方式重新 `build`，寄出的信與預覽一致。
- `ClaimPackage.unavailable_attachments: list[UnavailableAttachment]`（預設空）：預覽時在 Drive 上取不到、不會附在信裡的文件。`UnavailableAttachment` 有 `document_id`、`file_name`、`reason`（`not_found` 已永久刪除／`trashed` 在垃圾桶），從 `app.contracts` 匯出。
- **7 號的做法**（`GmailClaimPackager`）：有 Drive 授權時逐一讀附件的檔案資訊（不下載內容）。取不到的不放進 `attachments`。同一項待辦已經重新上傳、有新的可附時，舊檔不附也不提示。沒有其他可附文件時：**需上傳的待辦列進 `missing_todo_ids`，平台就不讓寄出或建草稿**（一定要附的文件不能不處理）；不需上傳的才在信上的「未隨信附上的文件」寫待辦名稱加「（另行提供）」。信上不寫「請重新上傳」這類給使用者的話（信是寄給保險公司的）。`unavailable_attachments` 只列沒有其他可附文件的那幾份。沒有 Drive 授權、授權失效或暫時連不上時不能確定檔案在不在，照舊全部附上，寄出時 `send` 會再檢查一次。
- **送件頁**：預覽信上方用提示框列出取不到的檔案與原因，附「到 Google Drive 的垃圾桶還原」「到『上傳文件』重新上傳」的連結與「重新檢查」按鈕；送件包有還缺的待辦時「寄出」按鈕停用，說明「處理好之前不能寄出」；從「我自己處理就好」建立草稿被擋下（409）時，在詢問頁顯示同樣的提示框，說明改成「處理好之前不能建立草稿」。
- 待辦的勾選狀態與 `incident_todo`、`incident_document` 的資料都不動；不需要 migration。拉到要 `make client`。

## 2026-11-09　契約 v2.7.0：待辦帶出文件條件與「新增」標記、保單摘要帶出編號（選配，#232）

**版本號**：`CONTRACT_VERSION = "2.7.0"`。**只新增、選配**：6、7 號的程式不用改。
- `TodoView.condition`：這份文件的產生條件（`field`/`equals` 或 `fact`）。5 號在問答中修正描述、重新下結論時，用它判斷哪些待辦要送 `todo_applicability`。判斷函式 `condition_met()` 平台和 5 號共用。
- `PolicySummary.policy_id`：前端「有新狀況」用它在同一張保單開新事件。
- `TodoView.is_new`：狀況更新後才加入、或從不適用改回適用的待辦，畫面標「新增」，勾選（使用者或 6 號自動勾）後清除（規格 4.5 R5）。資料表的 `incident_todo.is_new` 本來就有，這次接上。
- 不需要 migration。拉到要 `make client`。

## 2026-11-09　契約 v2.6.0：保障範圍與結論精確到「節」（選配）

**版本號**：`CONTRACT_VERSION = "2.6.0"`。**只新增、選配（預設 `None`）**：沒帶節的實作行為完全不變，6、7 號不用改。接續 v2.5.0 的 `RuleRef.subsection`，處理 5 號反映的華南第三章分節問題。
- `CoverageRef`、`ClauseView`、`ClauseUpdate` 新增 `subsection: str | None`：章底下的節（例如「第二節 班機延誤保險(定額給付-累進式)」）。**沒有節的章、整份險種都是 `None`，維持章的層級**。
- **平台把事故類型對到的保障展開到節**（`ctx.event_types[].coverages`）：章底下有節的，每一節各一項；事故類型的關鍵字有節就比對**節名**、沒有節比對章名。例如華南「班機延誤」只對到「第二節 班機延誤保險」，不再整個「第三章 個人海外旅行不便保險」（章名含「旅行不便」，原本整章都會比對到）。`ctx.policy.coverages` 仍是方案設定的層級（章或整份險種），不變。
- `ClauseUpdate.subsection`：沒給就是整章；給了**必須搭配 `section`，而且必須是條款庫裡真的有的節**，不然整則回覆被拒絕（502，不讓 LLM 編節名）。同一章可以同時有多個節的結論（例如班機延誤適用、旅程取消不適用）。
- 資料表 `incident_clause` 新增 `subsection`，唯一限制改成 `(incident_id, insurance_id, section, subsection)`（migration）。
- 5 號 v1：結論從 `event.coverages` 帶出節；問答的條文範圍依結論的節限縮（結論是某一節就只查那一節與共同條款，結論是整章就查整章）；問答情境裡的保障名稱優先寫節名。前端結論卡顯示節名（去掉「第二節」的編號）。
- 拉到要 `make migrate`、`make client`。
- 給 5 號：用 `c.subsection` 原樣放回 `ClauseUpdate`（`event.coverages` 的每一項都已經是對的層級）；想自己縮小範圍時，檢索結果的 `RuleRef.subsection` 可以過濾。

## 2026-11-09　契約 v2.5.0：`RuleRef.subsection`，條文帶出所屬的節（選配）

**版本號**：`CONTRACT_VERSION = "2.5.0"`。**只新增、選配（預設 `None`）**：5、6、7 號的程式都不用改。
- `RuleRef`（`services.search_rules` 的檢索結果）新增 `subsection: str | None`：章底下的節，例如華南「第三章 個人海外旅行不便保險」底下的「第二節 班機延誤保險(定額給付-累進式)」。多數條款沒有節，是 `None`。
- 資料表 `insurance_rule` 新增 `subsection`（nullable，migration `912aee7b4026`）；`section` 仍然只是章，語意不變，所以 `CoverageRef`、`ClauseView`、方案的 `chapters`、保單代碼對照都不受影響。
- 解析器（`clauses.py`）認得「第 X 節」：節標題不再被併進上一條的內文（5 號反映華南第 29 條尾巴吃到「第三節 旅程更改保險(實支實付)」），並記在下一條起的 `subsection`；換章時節重新算。內容驗證的 `section_heading` 規則同步（`verify_profiles.toml`）。
- 送去算向量與 BM25 的文字（`embedding_text`）改成「險種名、章、節、條文序號、標題」加內文：章與節之前都沒有進去，同一份險種裡標題一樣的條（「承保範圍」「理賠文件」）只靠內文分辨。**改了之後所有條文都要重算向量**（`make reembed`），seed 檔也要重新匯出。
- 拉到要 `make migrate`、`make client`、`make seed`（seed 檔已更新），已經入庫的條文要重算向量才會套用新文字。
- 給 5 號：想只在某一節裡找條文（例如華南「班機延誤」）時，可以用 `RuleRef.subsection` 過濾檢索結果；**目前 `ctx.policy.coverages`、`ClauseView` 仍是章的層級**，要讓結論卡顯示節或用節限縮範圍，需要另外擴充（尚未做，先討論）。

## 2026-11-08　契約 v2.4.0：待辦的「適用」註記，5 號回報哪些待辦不適用（選配，#232）

**版本號**：`CONTRACT_VERSION = "2.4.0"`。**只新增、選配**：5 號沒給就不動任何待辦，6、7 號的程式不用改。
- `TodoView` 新增 `applicable: bool`（預設 `True`）；`IncidentReply` 新增 `todo_applicability: list[TodoApplicability]`（`{todo_id, applicable}`，預設空）。資料表 `incident_todo` 新增 `applicable`（預設 true，migration `0d7b4f30b33f`）。
- **只是 1/0 註記**：不改待辦原本是待辦或已完成（`status`），也不動已上傳的文件。兩個方向都能設，所以結論改回來時 5 號把它設回 `True` 就恢復；沒列到的待辦不動。
- 規則：`todo_id` 必須是**這個事件自己的**待辦；不存在、屬於別的事件、或行程共用的待辦（理賠申請書 D10，`scope = "policy"`）都算違反契約，整則回覆不寫（502）。
- **`applicable = False` 的待辦當作不存在**：`all_todos_done`（送件前的檢查）不算它；不能勾選、不能上傳文件、不能把文件確認到它（409）。**交給 6、7 號的 `ctx.todos` 平台已經濾掉它**（`IncidentContext.for_agents_6_7()`），所以 6 號不會把文件對到它、7 號不會附它的文件、「未附文件」與缺的待辦也不列它；已上傳的文件留在資料裡，只是對不到待辦。5 號拿到的 context 與 API 回給前端的是完整清單，帶 `applicable`。
- 舊的 `status = "not_applicable"` 保留在型別裡但不再寫入，之後 #232 收尾時再決定要不要拿掉。
- 拉到要 `make migrate`、`make client`（`TodoView`、`IncidentReply` 都在 OpenAPI 裡）。
- 給 5 號：判斷某些待辦不再需要時，把 `{todo_id, applicable: false}` 放進 `todo_applicability`；結論改回來就送 `applicable: true`。仍然不能刪待辦、不能改 `is_done`。
- 給前端：待辦依 `applicable` 收起不適用的項目；不適用的待辦勾選與上傳會回 409。

## 提案（尚未實施）　7 號對 v2.1 之後的需求：多封信（暫緩）（7 號，2026-11-07，11-08 更新）

> **狀態：提案，契約型別沒有改**（提出時是 2.1.0；原本的「預覽時檢查附件」已在 2.8.0 實作，見最上面那一筆，剩下的都還沒做）。由 7 號開發者提出，等平台負責人決定；定案後平台改契約時，請把這段換成正式的變更紀錄。
> 依據：#154（7 號建立草稿已接上，見下方「7 號這邊已做的」）、[ADR-0025](../../adr/0025-claim-submission-fill-before-send.md)、`docs/specs/agent-7-package.md`「需要平台處理」第 2 項、`docs/integration-plan.md`「已知契約缺口」的 7 號那條。
> 原則照舊：只新增、有預設值，v2.1 的實作與呼叫方式不改也能跑。

**7 號這邊已做的（不需要改契約）**
- `mode="draft"`：在使用者的 Gmail 建立草稿，回 `drafted`，`external_ref` 是 Gmail 的**草稿編號**（`drafts.create` 回傳的 `id`，不是草稿裡那封信的編號）。有空格也能建，收件者可以沒有；沒有 Gmail 或 Drive 授權時回 `failed`、`reason` 說明要授權哪個。
- 建立草稿後只回 `drafted` 加草稿編號就夠了：使用者選擇建立草稿之後平台不再協助處理任何事，不需要草稿裡那封信的編號或打開草稿的連結；結案後送件頁只顯示「已結案」、不分是怎麼結案的（2026-11-08 使用者確認）。
- 寄出與草稿用同一份主旨、內文與附件；草稿另外加一份把「（請填寫＋項目）」黃底紅字標出的 HTML 版本。附件檔名重複時加「_序號」（#74）。
- 事故摘要的地點：`destination` 沒有時用 5 號記下的事實 `place`（#165）。`place` 已在 `ctx.facts` 裡，這項不需要改契約。

### 1. 多封信（一次送件拆成多封）：暫緩

> **暫緩**（2026-11-08 7 號決定）：目前只有班機延誤一種事故類型，附件 3～4 個、加起來不到 1 MB，一封信就裝得下，沒有需要拆信的情況，也測不到。等有第二種事故類型、整張保單一起送件，或附件可能超過 Gmail 一封約 25 MB 的上限時再決定。下面保留原本的想法給那時參考，平台現在不用做。

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

### 2. 其他（已在 7 號規格，列在這裡方便一起決定）
- `build_for_policy(policy_ctx)`：整張保單送件，`policy_ctx` 含保單、底下所有事件與其文件、D10 的文件；D10 只附一次。
- **契約測試的整條流程**：`test_full_flow_from_message_to_submission` 寄出時只帶 `recipient`、沒帶 `fills`。真的 7 號一定有平台沒有的空格（被保險人姓名、保單號碼、聯絡電話），平台在呼叫 7 號之前就回 409，所以 `CONTRACT_AGENT_7=gmail-offline make test args="-k contracts"` 在 main 上本來就失敗（2026-11-07 確認，跟 #154 的改動無關）。請平台在這個測試帶上 `fills`（項目從預覽的信裡找「（請填寫＋項目）」），並給 Drive、Gmail 的假授權。7 號不改契約測試。
## 2026-11-08　契約 v2.3.0：`MessageView` 帶出回覆的快速選項與出處（選配，#212）

**版本號**：`CONTRACT_VERSION = "2.3.0"`。**只新增、選配（預設空 list）**：5、6、7 號的程式都不用改，也不用升版。
- `MessageView`（`IncidentContext.messages` 的每一則）新增 `quick_replies: list[str]` 與 `citations: list[Citation]`。5 號回覆附的快速選項與引用的條文出處，平台本來就有存（`Message.quick_replies`、`MessageCitation`），現在帶出來，前端重新整理後才能還原。**使用者的訊息兩者都是空的**；每則 5 號訊息各自帶自己的。
- `Citation` 從 `incident_agent.py` 移到 `common.py`（`from app.contracts import Citation` 與 `from app.contracts.incident_agent import Citation` 都照舊能用）。
- 不需要 migration，不建新資料表。拉到要 `make client`。
- 給 5 號：`ctx.messages` 裡 5 號自己先前的回覆現在多了這兩個欄位，可以忽略；要用的話，`citations` 是程式從檢索結果寫入的出處，不是 LLM 寫的。

## 2026-11-07　契約不變（仍是 2.2.0）：理賠文件規則依 Excel「事故理賠文件」修正（#194）

**契約檔案沒有改**；改的是 `incident_catalog.json`。原則：Excel 有列的文件才列成待辦（沒列的列成待辦，旅客只能勾「未附文件」，送件信會寫「另行提供」）。
- **不再有任何類型列 D11（存摺與護照影本）**：`always_documents` 清空，`flight_delay` 的 `exclude_documents` 拿掉。醫療類的重大注意事項加「保險公司匯款時可能會跟你要存摺封面，可先準備」。
- **新增 D24「準備受益人身分證明」**，只加在醫療類（`injmed`、`illmed`）；辨識關鍵字留空，6 號辨識不出來時會進「需要你確認」，由旅客自己選待辦，辨識規則由 6 號之後補。
- **行李延誤不再列 D07**（購買必需品的收據）：Excel 的行李延誤是定額給付，沒有收據。
- 班機延誤、行李延誤、行李損失、證件遺失的重大注意事項加「如果你的保單是華南產物，請另外附上損失清單及費用支出單據」（catalog 還不分保險公司，先用提醒，不擋送件）。
- **D17 改成「取得重新申辦旅行文件的證明（例如新護照或入國證明書）」**，`notes` 一併改寫。
- 舊的開發資料庫要執行一次 `make seed`，舊範本才會清掉；已用舊範本建立的事件待辦保留。

## 2026-11-07　契約不變（仍是 2.2.0）：保單解析與確認畫面（#184）

**契約沒有改**：`IncidentContext` 與 `PolicySummary` 的欄位、型別、語意都和 2.2.0 一樣，`start_date`、`end_date` 仍是日期。5、6、7 號不用動。
- `policy` 資料表新增 `start_at`、`end_at`（含時區，台北時間，只有上傳保單會填；migration `b7c41d2e9a10`）。**還沒進契約**：要讓 5 號判斷到小時時，需要先討論契約變更。
- `Policy.destination` 開始有值（上傳時由保單的旅遊國家帶入、確認畫面可改）；契約裡的 `IncidentContext.destination` 仍來自事件，不是保單。
- `PolicyOut` 新增 `company`、`destination`、`start_at`、`end_at`；上傳回應多 `product_name`、`riders`、`auto_filled`；新增 `PATCH /policies/{id}`。拉到要 `make migrate`、`make client`。
- 方案可標 `upload_only`（保單專用方案），`GET /plans` 不列出。
- 細節與決定見 [policy-parsing-184.md](policy-parsing-184.md)、[ADR-0026](../../adr/0026-upload-only-plans-for-official-site-products.md)。

## 2026-11-07　契約 v2.2.0：確認「不確定」的文件後改檔名（選配，#160）

**版本號**：`CONTRACT_VERSION = "2.2.0"`。**只新增、選配**：沒實作的 6 號照樣能跑，只是確認後檔名維持「待確認」。
- 新的 `DocumentRenamer`（`app.contracts` 匯出，`runtime_checkable`）：`rename_confirmed(ctx, document, todo, user, google) -> str | None`。使用者確認一份「不確定」的文件、對上待辦之後，平台若發現 6 號的實作有這個方法就呼叫，**回傳新檔名**；平台把資料庫的檔名也改成它。改不了（沒授權、雲端失敗）回 `None`，平台沿用舊檔名，確認照常完成。
- 為什麼要 6 號改：送件信的附件檔名是寄信時從 Drive 讀的，只改資料庫的話預覽是對的，寄出去的信附件還是「待確認_1.pdf」。
- 6 號的實作（`DocumentAgent`）：Drive 檔案改名（`DriveStorage.rename`，PATCH `files/{id}`）；檔名規則同上傳（事故類型_待辦名稱_序號，D10 是理賠申請書_序號）。序號算「辨識通過或使用者確認過」的文件數，**不含正在改名的那份**，兩份確認到同一待辦會是 `_1`、`_2`。
- `DriveStorage` 協定多一個 `rename`：自己實作 `DriveStorage` 的人（測試替身、評估）要補。
- 沒有 migration；`make client` 不受影響（沒改 API）。

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

# 前端交接：出事了（理賠）流程

給接手這條流程畫面的前端組員，以及你們使用的 AI 助手。
流程已經串好、能從首頁走到送件，樣式只用 Tailwind 基本款，**沒有做視覺設計**，這部分交給你們。
5、6、7 號 agent 目前是假實作，真實作上線後的差異在最後一節。名詞以根目錄 [GLOSSARY.md](../../../GLOSSARY.md) 為準：程式、路由、文件用「事件」，畫面文案對使用者可以說「理賠」。

## 先跑起來

```bash
make doctor                                  # 全部 PASS 才繼續
make seed                                    # 條款庫、方案保費、事件類型、待辦範本
# 然後開 http://localhost:5173 ，用測試登入，按首頁的「出事了：幫我處理理賠」
```

- **不想起後端**：用假資料模式 `VITE_MOCK=true`（`src/mocks/incident.ts`）。重新整理會回到最初狀態，最初有兩個事件：`…0050`「可送件」（待辦全完成）與 `…0051`「已完成」，打開就能看到後面兩個步驟。假資料的 5 號第二次回答後才判斷出班機延誤；上傳檔名含「證明」「收據」「診斷」才辨識通過，其他進「需要你確認」。
- 假資料模式沒有 Playwright 可跑的 e2e（測試的 `request` 不經過 MSW）；真後端的 e2e 是 `make e2e args="incident-flow"`。
- 前置條件：條款庫、方案保費、事件類型與待辦範本都要有資料。`config/incident_catalog.json` 目前只是**範例內容**，正式內容由後台維護；沒有資料時建立事件會失敗，請先 `make seed`。

## 路由與檔案

| 路徑 | 檔案 | 畫面 |
| --- | --- | --- |
| `/` | `routes/_authed.index.tsx` | 兩張入口卡片，第二張連到 `/incident/new` |
| `/incident/new` | `routes/_authed.incident.new.tsx` | 選保單（現有的、上傳、或自己選方案與保額）→ 說明發生什麼事 → 我的事件列表 |
| `/incident/$id` | `routes/_authed.incident.$id.tsx` + `.index.tsx` | 外框（標題、狀態、三步驟）；步驟 1：對話、待辦、事件狀況、適用保障、重大注意事項 |
| `/incident/$id/documents` | `…$id.documents.tsx` | 步驟 2：上傳文件、辨識結果、「需要你確認」的文件對到待辦 |
| `/incident/$id/submit` | `…$id.submit.tsx` | 步驟 3：預覽送件包、收件人、送件 |

共用的樣式與 hook 在 `features/incident/shared.ts`：

- `useIncident(id)`：三個步驟頁共用同一份快取（`getIncident`），任一頁更新後其他頁立刻看到。
- `useLatestReply(id)`：5 號最近一次的回覆（快速回覆、出處）。只存在這個分頁，**重新整理就沒有**，因為後端不存回覆。
- `errorText(error, status)`：後端錯誤轉成給使用者看的句子，所有錯誤顯示都走這個。

`/dev/incident` 是給 5、6、7 號開發者的測試台，會原樣顯示契約違規訊息，**不要改成正式畫面**；兩邊互不影響。

## 各步驟用到的 API

函式名就是 OpenAPI 的 operationId，也是 `src/client` 的函式名（不手改，改了 API 後 `make client`）。

| 步驟 | 動作 | 函式 | 備註 |
| --- | --- | --- | --- |
| 選保單 | 列出我的保單 | `listPolicies` | |
| | 上傳保單 PDF | `POST /policies`（`fetch` + `FormData`） | 比對不到方案回 422，訊息可直接顯示 |
| | 方案下拉選單 | `listPlans` | |
| | 該方案可投保的保額 | `listPlanSumInsuredOptions` | 各方案不同（ADR-0018），選了方案才查 |
| | 手選建立保單 | `createPolicyManual` | 保額不在該方案範圍、結束日早於開始日回 422；保險期間選填 |
| 開始 | 建立事件 | `createIncident` | 回 `{reply, incident}`，`reply` 是 5 號的第一個問題 |
| | 事件列表 | `listIncidents` | |
| 步驟 1 | 讀事件 | `getIncident` | 回的就是 `IncidentContext` |
| | 使用者說話 | `sendIncidentMessage` | `input_mode` 是 `text` 或 `quick_reply` |
| | 勾選／取消勾選待辦 | `patchIncidentTodo` | 回新的 `IncidentContext` |
| 步驟 2 | 上傳文件 | `POST /incidents/{id}/documents`（`fetch` + `FormData`，欄位 `file`） | 回 `DocumentOut`；之後要重新讀事件，因為 6 號可能勾了待辦 |
| | 確認「需人工確認」的文件 | `confirmIncidentDocument` | 使用者自己選要對到哪一項待辦 |
| | Google 授權狀態 | `googleGrantStatus` | 只有 Google 登入的使用者才查 |
| 步驟 3 | 預覽送件包 | `getIncidentPackage` | |
| | 送件 | `submitIncident` | body：`mode`（`send`｜`draft`｜`self`）、`fills`（空格 → 值）、`recipient`；回 `SubmissionOut`（`status`：`sent`｜`drafted`｜`self_submitted`｜`failed`）。目前正式送件頁只用 `send`，新流程見 #153 與 ADR-0025 |

## 狀態

**事件**：`status` 是 `open`／`completed`。送件成功後變 `completed`。**結案後鎖住**：傳訊息、改待辦、上傳與確認文件、再送件一律回 409「事件已結案，不能修改」；讀取（看事件、看送件包）照常。畫面在 `completed` 時應該停用這些操作，不要等使用者按了才看到錯誤。建立事件的當下 `todos` 是空的、`incident_type_*` 是 `null`，待辦要等 5 號判斷出類型才會出現（畫面要有「說明完才會列出」的空狀態）。

**待辦（`TodoView`）**

| 欄位 | 值 | 畫面 |
| --- | --- | --- |
| `status` | `pending`／`done`／`not_applicable` | 不適用的不能勾（後端回 409） |
| `done_by` | `user`／`agent`／`null` | `agent` 顯示「系統確認」 |
| `requires_upload` | bool | 沒完成時標「需上傳文件」 |
| `without_document` | bool | 需上傳的待辦被使用者手動勾掉，標「未附文件」（規格 v3.4） |
| `scope` | `incident`／`policy` | `policy` 是整個行程共用的理賠申請書，不屬於單一事件，但會出現在 `todos` 裡 |

**文件（`recognition_status`）**：`pending`（等待辨識）、`recognized`（辨識通過）、`needs_review`（需要使用者確認，確認前不會進送件包）、`incomplete`、`failed`。

**能不能送件**：所有 `pending` 待辦都完成（`not_applicable` 不算）才能送，前端用同一個條件停用送件按鈕；後端也會擋（409 `還有待辦沒完成`）。

## 錯誤

| 狀況 | 顯示 |
| --- | --- |
| 401 | `_authed` 外框已處理，會帶 `next` 轉到登入頁 |
| 404 | 事件／保單不存在或不是你的（別人的也回 404） |
| 409 | 送件時還有待辦沒完成、勾選不適用的待辦、**事件已結案**（見下）：訊息可直接顯示 |
| 413／415 | 上傳的檔案太大／不是 PDF（保單上傳）：訊息可直接顯示 |
| 422 | 保單比對不到方案、手選的保額不合法：訊息可直接顯示 |
| **502** | agent 的回傳不符合契約，**一筆都沒寫入**。只顯示「系統暫時無法處理，請稍後再試」，細節在後端 log |
| 送件 `status == failed` | 顯示 `reason`（沒授權 Gmail、寄送失敗等），事件不結案 |
| 送件 409「信裡還有要填寫的項目：…」 | `send` 時空格沒填完，訊息列出項目 |

## Google 授權

登入方式是 Google 的使用者，才需要授權 Drive（存文件）與 Gmail（寄信）；測試登入的帳號沒有授權，畫面要說明哪些功能不能用，不要靜默失敗。授權用到才請求（ADR-0020）：

- 文件步驟：點「選擇檔案」時 Drive 沒授權，就先擋下選檔視窗並跳說明（授權會整頁跳走，選好的檔案會不見）。
- 送件步驟：按「送件」時先確認 Drive，再確認 Gmail。
- 授權完用 `next` 導回原頁；元件在 `features/google/`。

## 已知限制（先知道，不用當成 bug）

- **後端沒限制誰能取消勾選**：`patchIncidentTodo` 可以取消任何已完成的待辦，包含 6 號辨識後勾的。前端先問一次再取消；要不要在後端限制是平台決定，目前沒做。
- **使用者可以勾需上傳的待辦**，後端標 `without_document`，之後的送件包就沒有這項文件。
- 5 號的 `follow_up_questions` 目前是空的，事故類型的必問欄位（日期、地點等）要等契約 v2 才進 `IncidentContext`。v2 之後對話可以改成逐題表單，現在只有自由輸入加快速回覆。
- 手選建立的保單沒有 PDF，所以沒有加購，內容未經保單驗證。目前不記來源（上傳／手選），7 號寄信也不會標示。
- 訊息的回覆是同步回來的；使用者在回覆還沒回來就換頁，晚到的回覆會覆蓋快取。需要的話改成每次都重新讀事件。
- 沒有做桌機以外的版面確認，也沒有無障礙檢查，只有基本的 label、`role="alert"`、`role="status"`。

## 假實作才會這樣，真實作會變

| 行為 | 假實作 | 真實作預期 |
| --- | --- | --- |
| 5 號判斷類型 | 回答兩次後固定判斷成班機延誤 | 依事件類型決定追問，最多 2 題有界追問（ADR-0011） |
| 6 號辨識 | 依檔名：含「證明」「收據」「診斷」通過，含 `bad` 失敗，其他需人工確認；不檢查 Google 授權 | 看文件內容；沒有 Drive 授權時回 `needs_review` 並說明「請先授權」 |
| 7 號寄信 | 不真的寄 | 沒有 Gmail 授權回 `failed` 並說明原因 |
| 回覆時間 | 很快 | 要查條款、呼叫 LLM，要好幾秒；送出後要有等待狀態，按鈕要停用避免重複送 |

真實作上線不需要改畫面的資料流，只要把等待狀態與錯誤文案調好。契約變更看 [contract-changelog.md](contract-changelog.md)；契約 v2 的規劃在 [contract-v2-proposal.md](contract-v2-proposal.md)。

# 功能二 UI 調整：作法與 Codex prompt

依據：`C:\project\gae265_03_group_project\UI_new\好險有你 (Copy).html`（可互動原型）。`UI 畫板/` 的 46 張 webp 與舊的 v1.8 畫板逐像素相同，所以**靜態畫面沒變，變的是原型的互動與文案**。組長口頭提的「從過去帶入」確切要求沒有寫在 UI_new 裡，見最後「待組長確認」。

## 差異表（原型 vs 現況）

| # | 位置 | 原型 | 現況 | 範圍 |
|---|------|------|------|------|
| A1 | 2-1 保單檔案 | 接受 `.pdf .jpg .jpeg .png`，文案「PDF、JPG、PNG，10 MB 內…」 | `PolicyStep.tsx` 只收 PDF，後端 `policies.py:168` 擋非 PDF | 前端＋後端（圖片要走 OCR／Azure DI，先確認解析器能吃圖） |
| A2 | 2-1 從過去帶入 | 手動模式、且有已完成推薦的比較時才顯示「從過去的比較帶入」；沒有比較就不顯示 | 同左（`ImportFromComparison` 沒有比較就 `return null`） | 組長要的可能是「上傳模式也能用」或「沒比較時顯示停用狀態＋說明」，待確認 |
| A3 | 2-1 | 沒有「我的保單」下拉、日期只有日期 | 有「我的保單」與可選時間 | 待確認是否保留（現況是 #214 之後依後端能力做的） |
| B1 | 2-3 理賠待辦 | 待辦區上方有**唯一的上傳入口** `upBox`：可多選、逐份三步驟「讀取內容→對應待辦→檢查規則」、進度條「正在處理 N 份 已完成 x／N」 | 上傳在 2-4 `DocumentsPage`，2-3 只有每項待辦的「上傳」按鈕與「上傳理賠文件」連結 | 前端；若要在 2-3 內完成上傳，需把 `DocumentsPage` 的上傳邏輯抽成共用 hook／元件 |
| B2 | 上傳結果摘要 | 「這次上傳 N 份：x 份已自動打勾、x 份追加到已完成的待辦、x 份不合格、x 份無法辨識、x 份辨識失敗」＋「看全部 N 份明細」展開，每份有原因（不合格：缺少…、檔案未保留） | 2-4 有辨識結果清單，沒有摘要列與展開 | 前端 |
| B3 | 待辦列 | 狀態晶片（N 份檔案／缺什麼文字／⏱ 等待／待上傳）、標籤（新增／AI 已打勾／不適用）、已附檔案逐份「刪除」（結案後不給） | 刪除是 `PlaceholderButton`（沒功能） | 前端＋後端（需新 endpoint 刪文件，改 OpenAPI 後 `make client`） |
| B4 | 提醒 | 「滿 24 小時仍缺文件，會寄提醒信到你的 Google 信箱。」＋「看提醒信範本」對話框 | 範本按鈕是 placeholder | 先做對話框（靜態範本）；寄信排程不在這張 |
| B5 | 送件區 | 結案後「下載全部文件」「到 Gmail 查看」 | placeholder | 先維持 placeholder，除非後端已有 endpoint |
| B6 | 上傳說明 | `?` tooltip：多選、手機拍照、10 MB、命名規則、存 Google Drive | 文案在 FileDrop description | 前端，照原型文案 |
| B7 | Drive 授權 | 第一次上傳前彈「授權 Google Drive」對話框（允許／取消） | 2-4 有 `authorize-drive` 按鈕 | 沿用現況，不改流程 |
| B8 | 示範模式 | 「按下後會上傳 6 份示範文件」 | 屬原型導覽，非產品功能 | **不做** |

## 做法（建議分四張票，一張一個 PR）

1. **2-1 保單上傳收圖片（A1）**：先查後端解析器能否吃 JPG／PNG；不行就只改文案並回報，不硬放。
2. **2-1 從過去帶入（A2／A3）**：依組長確認後的規則調整 `PolicyStep`／`ImportFromComparison`。
3. **2-3 上傳入口與結果摘要（B1、B2、B6）**：抽出共用上傳 hook，2-3 放 `upBox`，2-4 改用同一個元件（保留 `/incident/$id/documents` 路由與既有 testid）。
4. **待辦列細節（B3、B4）**：狀態晶片、刪除檔案（含後端 endpoint）、提醒信範本對話框。

## 硬約束（貼給 Codex）

- 先讀 `AGENTS.md`、`GLOSSARY.md`、`docs/agents/dev-environment.md`；跑任何東西前 `make doctor`。
- 價格、保額與任何數字不由 LLM 產生（ADR-0004）；不動 `backend/app/contracts/` 的契約。
- `frontend/src/client/`、`routeTree.gen.ts` 不手改；改 API 後 `make client`。
- 既有 `data-testid` 保留（`import-from-comparison`、`authorize-drive`、`open-todos`、`documents`、`go-submit`、`upload-later`、`todo-files`…），e2e 靠它們。
- 樣式用既有 token 與元件（`FileDrop`、`Segmented`、`DialogShell`、`PlaceholderButton`），不新增色碼；390 px 寬不能橫向捲動。
- 後端改動要加 pytest，前端行為要加／更新 Playwright（`make e2e` 本機跑，CI 不跑）；`make lint`、`make test` 全過才能 commit。
- Commit 訊息繁體中文加 Conventional Commits 前綴，一個 commit 只做一件事；不 push、不開 PR，等使用者確認。

## 給 Codex 的 prompt（第 3 張票為例，其他票換「任務」段）

```text
你在 gae265_03_group_project 工作（FastAPI + React/TanStack Router，名詞見 GLOSSARY.md）。
先讀 AGENTS.md 與 docs/agents/codex-function2-ui-prompt.md（含差異表與硬約束），再動手。

參考原型（唯讀，不要修改）：/mnt/c/project/gae265_03_group_project/UI_new/好險有你 (Copy).html
- 2-3：函式 scr23、upBox、upHTML、todoHTML、sendHTML
- 靜態畫板：UI_new/好險有你 UI 畫板/desktop_2-3.webp、mobile_2-3.webp

任務：
在行程頁（frontend/src/features/incident/TripPage.tsx）的「理賠待辦」上方加入「上傳理賠文件」入口，
行為對齊原型 upBox：
1. 可一次選多份（accept 為 PDF、JPG、PNG，每份 10 MB 內）；
2. 逐份顯示「讀取內容 → 對應待辦 → 檢查規則」，整體進度條「正在處理 N 份　已完成 x／N」；
3. 完成後顯示摘要「這次上傳 N 份：…」與「看全部 N 份明細」展開，每份有結果與原因；
4. 尚未授權 Google Drive 時，沿用 DocumentsPage 的授權流程；
5. 缺文件時顯示「滿 24 小時仍缺文件，會寄提醒信到你的 Google 信箱。」與「看提醒信範本」對話框（靜態範本）；
6. 已結案不顯示此入口。
把 DocumentsPage 的上傳邏輯抽成共用 hook／元件，2-4 改用它，路由與既有 data-testid 不變。
後端若需新 endpoint，先寫 pytest，改完 make client。

完成標準：make doctor、make lint、make test 全過；make e2e 中 incident 相關 spec 通過並新增本功能的 spec；
390 px 寬無橫向捲動；用瀏覽器截圖對照原型。
回報：改了哪些檔、與原型不一致之處、沒做的項目與原因。不要 commit／push，等我確認。
```

## 待組長確認

1. 「手動上傳時要有『從過去帶入』按鈕」指的是：(a) 上傳保單模式也要有；(b) 沒有過去比較時也顯示（停用＋說明）；還是 (c) 手動輸入模式永遠顯示？原型是「手動模式＋有比較才顯示」，與現況相同。
2. 「選擇要建立事件的保單後介面有些調整」是指 2-1 欄位（A3：拿掉『我的保單』？），還是 2-1 之後的頁面？
3. 保單檔案是否真的要收 JPG／PNG（A1）。

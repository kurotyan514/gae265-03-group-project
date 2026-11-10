# 功能二畫面再對齊（2-2～2-5）：交接說明

2026-11-10 寫。給 5、6、7 號負責人，以及你們使用的 AI 助手。名詞以 [GLOSSARY.md](../../../GLOSSARY.md) 為準。

> 一句話：**功能二的五個畫面在 #214 已經對齊過設計稿 v1.8；11/9 設計者又更新了畫板與原型，這次要把 2-2 到 2-5 再對齊一次。** 只改前端畫面與文案，不動後端、契約、資料表與 `src/client/`。

## 1. 分工

| 負責 | 畫面 | 設計稿截圖 | 主要檔案（只動自己的） |
| --- | --- | --- | --- |
| 5 號 | 2-2 描述事故、2-3 理賠頁（桌機改成**左邊對話、右邊待辦**） | `desktop_2-2`、`desktop_2-3`、`mobile_2-2`、`mobile_2-3` | `features/incident/ClarifyingView.tsx`、`DescribeChat.tsx`、`TripPage.tsx`、`TodoList.tsx`、`IncidentCard.tsx`；路由 `_authed.incident.$id.index.tsx`、`_authed.incident.new.$policyId.tsx` |
| 6 號 | 2-4 上傳理賠文件 | `desktop_2-4`、`mobile_2-4` | `features/incident/DocumentsPage.tsx`、`DocumentUploader.tsx`；路由 `_authed.incident.$id.documents.tsx` |
| 7 號 | 2-5 送件、2-5 確認信件（preview） | `desktop_2-5`、`desktop_2-5_preview`、`mobile_2-5`、`mobile_2-5_preview` | `features/incident/SubmitPage.tsx`、`SendBox.tsx`；路由 `_authed.incident.$id.submit.tsx` |

**避免互相衝突**：
- `TripPage.tsx` 與 `TodoList.tsx` 只有 5 號改。6 號要在 2-3 改上傳元件的內容，改 `DocumentUploader.tsx` 本身；它放在 2-3 的哪個位置由 5 號決定。
- `components/ui/` 的共用元件盡量不改。真的要加新元件，開新檔案、不改既有元件的屬性（別人正在用）。要改既有元件，先在群組講。
- **先合併再開工**：PR #260（2-3 上傳入口）與 #263（逐份處理清單）都在動上傳畫面；請 #260、#263 合併後，三個人再從最新 main 開分支。

## 2. 設計稿在哪裡（已放進 repo）

`docs/design/function2-ui/`：
- `DESIGN.md`：設計稿全文（給 AI 前端實作用，v1.8）。**先讀第 0、3、4 節，再讀自己畫面的第 7 節**：2-2＝7.9、2-3＝7.10、2-4＝7.11、2-5＝7.12、對話框＝7.13；元件規格在第 6 節（6.19 對話、6.22～6.29 行程狀態列、事故卡、待辦、上傳結果、送件區、信件預覽）；文案在第 10 節。
- `img/`：桌機（1440）與手機（390）截圖，檔名 `desktop_2-3.webp`、`mobile_2-3.webp` 這類。

> `DESIGN.md` 是 11/7 的版本，**11/9 的畫板與原型比它新**。兩者不一致時以截圖與原型為準，並把不一致的地方回報給使用者，不要自己猜。

可互動的原型（唯讀，不要修改，不在 repo）：`C:\project\gae265_03_group_project\UI_new\好險有你 (Copy).html`，WSL 路徑 `/mnt/c/project/gae265_03_group_project/UI_new/好險有你 (Copy).html`。用瀏覽器打開可以實際點；原始碼裡搜尋 `scr22`（2-2）、`scr23`（2-3）、`todoHTML`、`upHTML`、`sendHTML`、`scr25`（2-5），文案與互動都在裡面。看截圖的方法：用圖片檢視直接開 `docs/design/function2-ui/img/*.webp`。

## 3. 現況與已知差異

**公開的規則（三個人都要遵守）**
- 一個事件一頁；2-2 與 2-3 共用 `/incident/$id`，用 `incident_type_code` 切換（還沒有 → 2-2，問完 → 2-3）；2-2 建立前是 `/incident/new/$policyId`（送出第一句才建立事件）。
- **名詞**：我們叫「理賠頁」，不叫「行程頁」（GLOSSARY.md 的 _Avoid_）。設計稿截圖裡的「回行程頁」，實作維持「回理賠頁」，不要照抄。
- 沒功能的按鈕用 `PlaceholderButton`（反灰，點了跳 Toast「暫無作用」），不要藏起來也不要做假的。
- 價格、保額與任何數字不由 LLM 產生（[ADR-0004](../../adr/0004-llm-never-produces-numbers.md)）。

**5 號**
- 設計稿 2-2、2-3 都是**單欄**（最寬 1040px）。本次要求桌機改成雙欄：**左邊對話視窗、右邊待辦清單**。設計稿沒有這個版型，要自己設計，見第 4 節。
- 2-3 與設計稿已知的差異（實作前先對照確認，不只這幾項）：「有新狀況」在設計稿裡是**行程狀態列右側的按鈕**，現況是問答區底下的連結；待辦的刪除檔案是 `PlaceholderButton`（沒有後端 endpoint，維持反灰）；「新增」「不適用」標籤與待辦的狀態文字，對照截圖。
- 問答區的 `DescribeChat` 2-2 與 2-3 共用（`maxLength` 500／300、`minHeight` 320／180）；改版型時兩邊都要驗。

**6 號**
- 2-4 的上傳邏輯與 2-3 共用 `DocumentUploader`（#260）。#263 正在改成逐份處理清單，先合併它。
- 設計稿 2-4：「還缺的文件」卡（依事故分組）→ 虛線框「選擇檔案」（說明＋「授權 Google Drive 後上傳」）→ 動作列「回理賠頁」／「稍後再傳」（文件齊了變「去送件」）。上傳後才出現辨識結果卡。
- 設計稿的提醒信範本對話框（7.13）若現況是 placeholder，先做靜態範本，寄信排程不在這次範圍。

**7 號**
- 2-5 有三種狀態：文件未齊、詢問（「要由我們用你的 Gmail 幫你寄給保險公司嗎？」）、確認信件（內文可改、「（請填寫）」未填完不能寄出）。截圖只有後兩種，第一種看 DESIGN.md 7.12。
- 寄出前的確認對話框、結案後的畫面（`closed`）、寄送失敗與附件不可用的提示（`FailedNotice`、`UnavailableNotice`）現況已經有，**沿用，只對齊外觀**。
- Gmail 授權對話框、草稿詢問（`loadSaved`／`writeSaved`）的行為不改。

## 4. 5 號：桌機雙欄的建議版型（可調整，做完截圖給使用者確認）

- 斷點：手機（≤767px）維持現在的單欄與順序，**手機版不能變**；桌機雙欄從 `lg`（1024px）開始；容器從 `max-w-[1040px]` 放寬到約 `1280px`，兩欄各一半（左 5：右 7 也可以，以對話不被擠窄為準）。
- **2-3**：最上面是行程狀態列（整列寬）。左欄＝「問答」（對話卡，桌機用 `sticky top-…` 讓它在右欄捲動時留在畫面上）；右欄＝「狀況總結 → 重大注意事項 → 理賠待辦 → 送件區」，順序同設計稿。「完成」動作列放整頁最下面。
- **2-2**：右欄的待辦還不存在。建議右欄放一張說明卡：「描述完成後，這裡會依事故產生理賠待辦。」手機版不顯示這張卡。
- 左欄的對話區在桌機要有固定高度、內部捲動，輸入列貼底；不要讓整頁因為對話變長而把待辦推走。
- 這是設計稿以外的版型決定，**做之前先把版型草圖或截圖給使用者確認**，確認後再做 2-3 的細節。

## 5. 約定（三個人都一樣）

- **只用 token**。顏色、字級、圓角、陰影都用 `styles.css` 的 token；字級用 `t-page-title`、`t-section-title`、`t-label`、`t-body`、`t-caption` 這類 utility；不要寫死色碼或像素字級。設計稿名字對照：`text`＝`ink`、`accent`＝`leaf`、`surface-soft`＝`leaf-soft`、`bg`＝`paper`、`border`＝`line`、`accent-text`＝`leaf-text`、`highlight`＝`sun`、`alert`＝`coral`。
- **按鈕一律白底**，主要按鈕是 2px 品牌色框；一頁只有一個主要動作，放動作列最右邊。`buttons.ts` 的每個變體是**一整串** class，不要疊加（Tailwind v4 同屬性誰贏看 CSS 順序，不是 class 順序）。
- 綠色**文字**用 `leaf-text`；`leaf` 只給圖示、圓鈕底與 focus 外框。
- 優先重用 `frontend/src/components/ui/`（`PageHead`、`ActionBar`、`Field`、`Chip`、`ChatLog`／`ChatMessage`（屬性叫 `from`）／`AskBar`、`Pill`、`DialogShell`、`Toast`、`PlaceholderButton`…）。先開 `http://localhost:5173/dev/ui` 看一遍預覽頁。
- **`data-testid` 全部保留**（e2e 靠它們），只改被文案影響的文字斷言。
- 可點的東西用 `<button>` 或連結，不用 `<div onClick>`；切換類用 `aria-pressed`／`aria-expanded`。
- `src/client/`、`src/routeTree.gen.ts` 是產生的檔案，不手改。
- 手機版包在每一頁裡：斷點 767px，每頁驗收含「390px 下沒有橫向捲動」（做法見 `e2e/incident-describe.spec.ts` 最後一個測試）。

## 6. 怎麼驗證

- 每個畫面做完，用 Playwright 的 `page.screenshot` 截桌機（1440）與手機（390），**逐一對照** `docs/design/function2-ui/img/` 的截圖，不要只看測試通過。
- 本機跑：`make doctor` 全 PASS → `make lint` → 單一 spec 用 `cd frontend && pnpm exec playwright test <檔名>`（`make e2e args="…"` 沒有過濾效果）。
- 相關 e2e：5 號 `incident-describe`、`incident-trip`、`incident-flow`、`incident-reload`；6 號 `incident-documents`；7 號 `incident-submit`。登入用 `e2e/helpers.ts` 的 `login()`。
- **e2e 要用假 agent**：本機 `.env` 若設了真的 `AGENT_5/6/7_IMPL`，這些 e2e 會失敗；測 e2e 時改回 fake。完整 `make e2e` 不穩（第一輪常有逾時、會呼叫外部服務的測試偶發失敗），單獨重跑過就不是你的問題。CI 不跑 e2e，合併前請自己跑一次。
- 後端沒改，不用跑 `make test`，但 CI 會跑。

## 7. 工作方式

- 一個人一個分支、一個 PR，分支名建議 `feat/ui-2-2-2-3`、`feat/ui-2-4`、`feat/ui-2-5`。
- Commit 訊息用繁體中文加 Conventional Commits 前綴（`feat:`、`fix:`、`test:`），一個 commit 只做一件事；**commit 前先把訊息與檔案給使用者看，確認後才 commit**；不要自己 push 或合併。
- 不要 `git add` `.claude/settings.json`（個人權限設定）。
- 與設計稿不一致、或做不到的項目，列在 PR 描述的「沒做／不一致」，不要默默略過。

## 8. 給 AI 助手的開場提示

三份提示共用開頭，各自再加「任務」段。

**共用開頭**

```text
你在 gae265_03_group_project 工作（FastAPI + React／TanStack Router，名詞見 GLOSSARY.md）。
先讀：AGENTS.md、GLOSSARY.md、docs/agents/handoff/function2-ui-realign.md（本次任務的交接說明與約定）、
docs/design/function2-ui/DESIGN.md 的第 0、3、4 節與你負責畫面的第 7 節、第 6 節相關元件。
設計截圖在 docs/design/function2-ui/img/（用圖片檢視打開），可互動原型在
/mnt/c/project/gae265_03_group_project/UI_new/好險有你 (Copy).html（唯讀，不要修改）。
DESIGN.md 比 11/9 的截圖舊，兩者不一致時以截圖與原型為準，並回報不一致處。

規則：只改前端畫面與文案；不動後端、契約（backend/app/contracts/）、資料表與 frontend/src/client/、routeTree.gen.ts。
先看 frontend/src/components/ui/ 與 /dev/ui 已有的元件並重用；只用 token，不寫死色碼；按鈕變體是一整串 class，不疊加。
所有 data-testid 保留。名詞用「理賠頁」不用「行程頁」。沒功能的按鈕用 PlaceholderButton。
跑任何東西前先 make doctor；做完 make format 再 make lint；用 Playwright 截桌機 1440 與手機 390 對照設計截圖，
並確認 390px 無橫向捲動。e2e 要用假 agent（.env 的 AGENT_5/6/7_IMPL 設成 fake）。
先檢查現況與設計稿的差異並列給我，再動手。commit 前把訊息與檔案給我確認；不要 push、不要開 PR。
完成後回報：改了哪些檔、與設計稿不一致之處、沒做的項目與原因。
```

**5 號：任務**

```text
任務：對齊 2-2 描述事故與 2-3 理賠頁（DESIGN.md 7.9、7.10；截圖 desktop_2-2、desktop_2-3、mobile_2-2、mobile_2-3）。
你負責的檔案：features/incident/ 的 ClarifyingView、DescribeChat、TripPage、TodoList、IncidentCard，以及
routes/_authed.incident.$id.index.tsx、_authed.incident.new.$policyId.tsx。不要改 DocumentUploader（6 號）與 SubmitPage／SendBox（7 號）。
1. 先逐項對照截圖與現況，列出差異（已知：「有新狀況」改放行程狀態列右側；待辦狀態與標籤文案）。
2. 桌機版（≥1024px）2-2 與 2-3 改成雙欄：左邊對話視窗、右邊待辦事項清單；手機（≤767px）維持現在的單欄與順序。
   版型建議見交接文件第 4 節。這是設計稿以外的版型，先給我版型草圖或截圖確認，再做細節。
3. 對話在桌機要固定高度並內部捲動，輸入列貼底；2-2 右欄在還沒有待辦時放說明卡。
4. 更新 e2e（incident-describe、incident-trip、incident-flow、incident-reload），加桌機雙欄的測試與 390px 無橫向捲動的測試。
```

**6 號：任務**

```text
任務：對齊 2-4 上傳理賠文件（DESIGN.md 7.11、7.13 提醒信範本；截圖 desktop_2-4、mobile_2-4）。
你負責的檔案：features/incident/DocumentsPage.tsx、DocumentUploader.tsx，routes/_authed.incident.$id.documents.tsx。
DocumentUploader 也用在 2-3（TripPage，5 號負責），改它時保持對外屬性不變，並確認 2-3 仍可用。
先確認 PR #260、#263 已合併，從最新 main 開分支。
1. 逐項對照截圖與現況列出差異：「還缺的文件」卡依事故分組、虛線框「選擇檔案」與說明文案、
   「授權 Google Drive 後上傳」、動作列（回理賠頁／稍後再傳，齊了變去送件）、上傳後的辨識結果卡與每份的結果文案。
2. 按設計稿調整版面與文案；提醒信範本若現況是 placeholder，先做靜態範本對話框，寄信排程不做。
3. 更新 e2e（incident-documents），加 390px 無橫向捲動的測試。
```

**7 號：任務**

```text
任務：對齊 2-5 送件與確認信件（DESIGN.md 7.12、7.13 Gmail 授權與確認結案；截圖 desktop_2-5、desktop_2-5_preview、mobile_2-5、mobile_2-5_preview）。
你負責的檔案：features/incident/SubmitPage.tsx、SendBox.tsx，routes/_authed.incident.$id.submit.tsx。
三種狀態都要對照：文件未齊、詢問、確認信件（含「（請填寫）」未填完的錯誤列與寄出鈕停用）。
寄出確認對話框、結案畫面、FailedNotice、UnavailableNotice、草稿詢問的行為沿用，只對齊外觀與文案。
1. 逐項對照截圖與現況列出差異（信件預覽的列版型、附件清單、錯誤列文案、動作列）。
2. 按設計稿調整；更新 e2e（incident-submit），加 390px 無橫向捲動的測試（兩種畫面）。
3. 寄信與 Gmail 的真實驗收（#155）不在這次範圍。
```

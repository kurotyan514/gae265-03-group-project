# 功能一畫面改版：交接說明

2026-11-08 寫。給接手的人，以及你們使用的 AI 助手。用字盡量白話；名詞以 [GLOSSARY.md](../../../GLOSSARY.md) 為準（在意事項、比較紀錄、推薦方案、推薦保額、情境試算）。

> 一句話：**功能二（出事了）的五個畫面已經改成設計稿 v1.8 並合併；功能一（出發前：幫我選方案）的 1-1 到 1-4 還是舊的灰色樣式，要換成同一套。** 共用元件已經有一批，缺的幾個要自己做。後端、契約、資料表都不用動，也沒有新的 API。

## 1. 現況

| 畫面 | 路由 | 檔案 | 狀態 |
| --- | --- | --- | --- |
| 1-1 輸入旅遊背景 | `/compare/new`（新建）、`/compare/$id/background`（修改） | `features/compare/BackgroundForm.tsx`（194 行）、`routes/_authed.compare.new.tsx`、`routes/_authed.compare.$id.background.tsx` | **舊樣式** |
| 1-2 選擇最在意的點 | `/compare/$id/concerns` | `routes/_authed.compare.$id.concerns.tsx`（120 行） | **舊樣式** |
| 1-3 推薦方案與比較表 | `/compare/$id/result` | `routes/_authed.compare.$id.result.tsx`（270 行，內含 `PlanCard`、`Benefits`） | **舊樣式** |
| 1-4 情境試算與問答 | `/compare/$id/scenarios` | `routes/_authed.compare.$id.scenarios.tsx`（347 行，內含 `ScenarioCard`、`Chat`） | **舊樣式** |
| 名詞解釋 | （對話框） | `features/compare/TermDialog.tsx` | 舊樣式 |
| 全部比較 | `/compare` | `routes/_authed.compare.index.tsx` | 已完成（#195） |
| 首頁「最近的比較」 | `/` | `routes/_authed.index.tsx`、`features/compare/ComparisonRow.tsx` | 已完成（#195） |

「舊樣式」指灰色的 `rounded-md border`、`bg-gray-*`、`text-red-600` 那一類寫法。**資料與行為都是對的，只換外觀、版型與文案。** 不要動 API、`src/client/`（產生的檔案）與後端。

## 2. 設計稿在哪裡

設計稿**不在這個 repo 裡**，只在某位成員的電腦上與兩個 Artifact：

- 檔案：`C:\project\gae265_03_group_project\upload_test\CI_sample\`（WSL 路徑 `/mnt/c/project/gae265_03_group_project/upload_test/CI_sample/`）：`DESIGN.md`（給 AI 前端實作用，v1.8）、`design-tokens.json`、`haoxian-design-spec/`（`tokens.css`、`tailwind.preset.js`）
- 設計規範的 Artifact：<https://claude.ai/artifact/SK9XserNUZLW7uqBdDhzeW>（原型 HTML，可以點開實際操作）
- UI 畫板的 Artifact：<https://claude.ai/artifact/KcksWPh1hmfNqV2qVyFeBe>（每個畫面的桌機 1440 與手機 390 截圖，功能一是 1-1、1-1 已填寫、1-1 驗證錯誤、1-2、1-2 已選 3 項、1-3、1-3 展開、名詞解釋對話框、1-4、1-4 問答進行中）

**建議把 `DESIGN.md` 與 `design-tokens.json` 放進 repo（例如 `docs/design/`）**，不然下一個人又要去找。這次沒有放，因為沒人要求，而且檔案是設計者的。

看畫板圖的方法：用 Artifact 的 read 加 `paths: ["img/desktop_1-3.webp", ...]` 把圖存到本機，再用圖片檢視看。檔名是 `desktop_<畫面>.webp`、`mobile_<畫面>.webp`，例如 `desktop_1-3_expanded`、`desktop_dialog_term`。

`DESIGN.md` 裡和功能一有關的段落：

| 段落 | 內容 |
| --- | --- |
| 0、3、4 | 實作規則、token、版面與 RWD（**先讀**） |
| 7.4 到 7.7 | 1-1 到 1-4 的畫面規格 |
| 6.6、6.7 | 表單欄位、天數提示 |
| 6.8 | 在意點卡 |
| 6.11、6.12、6.13 | 方案卡、推薦理由卡、名詞連結 |
| 6.14、6.15 | 標籤、保障比較表 |
| 6.16、6.17、6.18 | 分頁、情境故事、試算卡與小表 |
| 6.19、6.20、6.21 | 對話、Chip、提問列 |
| 6.30、6.31 | 對話框、載入遮罩 |
| 10 | 文案語氣與固定文案 |

## 3. 已經有、可以直接用的元件

功能二那批做在 `frontend/src/components/ui/`，**優先重用，不要另外發明**：

| 元件 | 用在功能一哪裡 |
| --- | --- |
| `PageHead` | 每頁開頭：麵包屑「出發前：幫我選方案 · 1／3」、H1、說明、小註（1-3 的「示意資料，非實際報價」） |
| `ActionBar`（`.Push`、`.Full`） | 每頁的動作列；手機兩欄、主要按鈕移到最上面整列 |
| `buttons.ts`（`btn`、`btnPri`、`btnSm`、`btnSmPri`、`lnk`、`wide`） | 按鈕與文字連結 |
| `Field`、`fieldInput`、`FieldHint`、`FieldError`、`FieldOk`、`FieldWarn`、`RequiredMark` | 1-1 表單欄位與驗證訊息 |
| `Chip`、`ChipGroup` | 1-4 的常見問題 |
| `ChatLog`、`ChatMessage`（屬性叫 `from`，`me`／`ai`）、`ChatDivider`、`AskBar` | 1-4 問答（`AskBar` 上限 300 字） |
| `ConclusionPill`、`Pill`、`ProgressPill`、`FactPill` | 1-4 AI 回答的結論 Pill |
| `DialogShell`、`PickRow` | 名詞解釋對話框（換掉 `TermDialog` 的樣式） |
| `Toast`、`PlaceholderButton` | 沒有功能的按鈕就用反灰按鈕（點了跳「暫無作用」） |

另外 `features/incident/shared.ts` 的 `card`（卡片外觀，不含內部間距）與 `box` 也可以用。**`/dev/ui` 是這批元件的預覽頁**（只在非 production 有），先去看一遍。

## 4. 還沒有、要自己做的元件

這些在 `DESIGN.md` 第 6 節有規格，目前 repo 裡沒有：

| 元件 | 規格 | 用在 |
| --- | --- | --- |
| `DaysSummary` | 6.7（天數提示，`aria-live="polite"`） | 1-1 |
| `ConcernCard` | 6.8（選中框、右上角排序圓、選滿 3 項時其餘停用、`aria-pressed`） | 1-2 |
| 九個在意點圖示 | 5.3、7.5（clock、xcal、bag、med、id、card、pulse、warn；線條 stroke 2） | 1-2；放進 `components/icons.tsx` |
| `PlanCard` | 6.11（推薦卡 3px 品牌色框、保額下拉、「保額（已自行調整）」提示） | 1-3 |
| `ReasonCard` | 6.12（「看推薦依據」展開，箭頭旋轉 200ms） | 1-3 |
| `TermButton` | 6.13（保障項目名稱加 ⓘ，點了開名詞解釋） | 1-3、1-4 |
| `ComparisonTable` | 6.15（桌機三欄，手機兩欄：項目名稱整列、下面推薦與次推薦並排；「你在意 N」標籤） | 1-3 |
| `Tabs` | 6.16（涵蓋你在意點的分頁加 ★ 並排前面） | 1-4 |
| `Story`、`SimulationCard`、`MiniTable` | 6.17、6.18 | 1-4 |
| 載入遮罩 | 6.31（「正在比較方案…」，`role="status"`） | 1-2 按下一步之後 |

通用的放 `components/ui/`，只有功能一用到的放 `features/compare/`。

## 5. 每一頁要保留的行為與要改的地方

下面的「行為」是現有 e2e 在驗證的，換樣式時不能弄壞。

**1-1 輸入旅遊背景**（7.4）
- 行為：目的地（16 個地區）、出發日、回程日、年齡；即時驗證，錯誤串成一行：出發日要從今天起、回程日不能早於出發日、旅遊天數最長 10 天、年齡 15 到 80 的整數；四欄位都填且沒錯才能按「下一步」；`/compare/new` 新建、`/compare/$id/background` 修改已存的紀錄；`data-testid="trip-days"` 保留。
- 改成：窄版卡片表單、`PageHead`、`Field`、`DaysSummary`、動作列只有「下一步」（主要）。

**1-2 選擇最在意的點**（7.5）
- 行為：九個在意點，最多選 3 項、點選順序就是重要程度、取消後後面的補位；「其他在意的事」選填、200 字、有計數；上一步／下一步；沒選任何一項不能下一步。
- 改成：`ConcernCard` 格、textarea 加計數、按下一步後顯示載入遮罩「正在比較方案…」；**條件沒變時直接到 1-3，不重算**（現在的行為是什麼，先讀程式再對照設計）。

**1-3 推薦方案與比較表**（7.6）
- 行為：沒有推薦（還沒選在意點）就導回 1-2；推薦與次推薦兩張方案卡，各自可改保額（用 `updateComparison` 存，重新整理還在）；推薦理由與「看推薦依據」；比較表把疾病醫療合成一列、你在意的項目標「你在意」、意外醫療不標；點保障項目開名詞解釋（含兩個方案各自的條款依據）。
- 改成：`PlanCard`、`ReasonCard`、`ComparisonTable`、動作列「上一步／情境試算與問答（主要）／完成」；列的順序是你在意的項目（依在意順序）、三大主項、「看全部項目」之後才出現其他；小註「示意資料，非實際報價」；免責「僅供比較參考，非投保建議。保費以保險公司官網試算為準。」
- 設計還要求「沒有符合方案時」的畫面（標題「沒有符合條件的方案」，只有上一步）。**現有程式有沒有這個狀態，請先確認**；如果後端不會回這種情況，就不用做。

**1-4 情境試算與問答**（7.7）
- 行為：五個固定情境的分頁（涵蓋你在意點的加 ★ 並排前面）；每個情境有故事、假設、試算卡（多列）；沒有推薦就導回 1-2；問答：離開再回來對話是空的（不保存）；點短名稱與給付方式開解釋。
- 改成：`Tabs`、`Story`、`SimulationCard`（chip「模板試算・不經 AI」）、`ChatLog` 加常見問題 `Chip`（「兩個方案差在哪？」只有一個方案時不顯示）、`AskBar`（300 字）、空對話時的說明文字、動作列「回比較表／完成」。

## 6. 約定與從功能二學到的做法

- **只用 token。** 顏色、字級、圓角、陰影都用 `styles.css` 裡的 token（`brand`、`heading`、`ink`、`muted`、`leaf`、`leaf-text`、`leaf-soft`、`line`、`paper`、`sun`、`coral`、`danger*`、`warn*`）。設計稿的名字對照：`text`＝`ink`、`accent`＝`leaf`、`surface-soft`＝`leaf-soft`、`bg`＝`paper`、`border`＝`line`、`accent-text`＝`leaf-text`、`highlight`＝`sun`、`alert`＝`coral`。字級用 `t-page-title`、`t-section-title`、`t-label`、`t-body`、`t-caption` 這類 utility（桌機與手機的值寫在同一個 class 裡）。
- **按鈕一律白底**，主要按鈕是 2px 品牌色框，不是實心綠。一頁只有一個主要動作，放動作列最右邊。
- **綠色「文字」用 `leaf-text`**（對比夠）；`leaf` 只給圖示、圓鈕底與 focus 外框。
- **Tailwind v4 的坑**：同一個屬性的兩個 class，誰贏取決於產生的 CSS 順序，不是 class 寫的順序。所以按鈕變體都是「一整串」class，不要把 `btn` 和 `btnPri` 疊在一起。
- **沒有功能的按鈕**用 `PlaceholderButton`（反灰、點了跳「暫無作用」），不要藏起來也不要做假的。
- **`data-testid` 全部保留**，e2e 靠它們；只改被文案影響的文字斷言。
- **手機版包在每一頁裡**：斷點 767px，照 `DESIGN.md` 4.2；每頁驗收含「390px 下沒有橫向捲動」。
- 動作列在手機用 `<ActionBar twoColumns>`，主要按鈕包在 `<ActionBar.Push><ActionBar.Full>…`。
- 可點的卡片、列、Logo 都是 `<button>` 或連結，不要用 `<div onClick>`；切換類元件用 `aria-pressed`／`aria-expanded`。
- 提交前 `make format` 再 `make lint`（biome 會重排程式碼；`biome-ignore` 註解要放在它要忽略的那一行正上方）。

## 7. 怎麼驗證

- 畫面：每一頁做完，用 Playwright 的 `page.screenshot` 截桌機與手機圖，**對照畫板**，不要只看測試通過。
- e2e 要更新的：`e2e/compare-background.spec.ts`（1-1、1-2）、`e2e/compare-result.spec.ts`（1-3）、`e2e/compare-scenarios.spec.ts`（1-4、1-2 到 1-4 的串接）。每頁加一個 390px 無橫向捲動的測試（做法見 `e2e/incident-describe.spec.ts` 最後一個測試）。
- **跑單一 spec 用**：`cd frontend && pnpm exec playwright test compare-result.spec.ts`。`make e2e args="…"` 的 args 沒有過濾效果，會跑全部。
- 在 e2e 裡登入用 `e2e/helpers.ts` 的 `login(page, email)`：登入後會輪詢 `/auth/me` 直到回 200；只等網址變成首頁，並行時偶爾會用還沒生效的登入去打 API，得到 401「未登入」。
- 後端沒改，所以不用重跑 `make test`，但 CI 會跑。

## 8. 接手時容易踩的坑

- **完整 `make e2e` 本機不穩，而且不是你的錯。** 每跑一次都有幾個偶發失敗，每次是不同的測試，單獨重跑都過。已知原因：改過檔案後的**第一輪**開發伺服器還在重新轉換模組，會有逾時，第二輪才準；會呼叫外部服務（Azure 嵌入、LLM）的測試偶爾逾時，功能一的 `compare-result`、`compare-scenarios`、`compare-background` 就是這類（推薦與問答會呼叫服務）。CI 不跑 e2e，所以合併前請自己在外部服務穩定時跑一次。
- `src/client/` 與 `src/routeTree.gen.ts` 是產生的檔案，不手改；新增路由檔後 `routeTree.gen.ts` 會自動更新，要一起 commit。
- 首頁與「全部比較」那一頁（#195）是更早做的，用了很多寫死的數字（`text-[22px]` 這類）而不是 `t-*` utility；那是舊寫法，功能一請用 `components/ui/` 的元件與 `t-*`，不要照抄。
- **`frontend-claim-flow.md`（出事了流程的前端交接說明）已經過期**：路由多了 `/incident/new/$policyId`、確認卡已拿掉、事件外框的步驟列已拿掉、上傳改成選檔即上傳。以功能二的程式為準，那份文件還沒更新。
- 沒有符合方案、保額已調整、只有一個方案這些邊界狀態，設計稿都有寫，請逐一對照現有程式，缺的先問負責後端的人，不要自己改後端。
- 設計稿的「完成」按鈕去哪裡、「情境試算與問答」的資料從哪來，現有程式已經處理了，沿用，不要重做。

## 9. 建議的切法

跟功能二一樣：**一張「共用元件」票**（第 4 節還沒有的元件，加圖示與載入遮罩，放進 `/dev/ui` 預覽），**再每一頁一張票**（1-1、1-2、1-3、1-4），後面幾張以第一張為前置；名詞解釋對話框跟著第一個用到它的頁面走。一張一個 PR；每張的驗收含：e2e 更新、390px 無橫向捲動、對照畫板的截圖、`make lint` 通過。

## 10. 給 AI 助手的開場提示

> 你在接手功能一（出發前：幫我選方案）的畫面改版。請先讀 `docs/agents/handoff/function1-ui-redesign.md`、`GLOSSARY.md`，再讀設計稿的 `DESIGN.md`（第 0、3、4 節，以及 7.4 到 7.7 與第 6 節和功能一有關的元件）。先看 `frontend/src/components/ui/` 與 `/dev/ui` 已經有哪些元件，**重用它們**；只做畫面，不改後端、契約、API 與 `src/client/`。每個頁面做完要截圖對照畫板、保留所有 `data-testid`、加 390px 無橫向捲動的測試。commit 訊息要先給使用者確認才能 commit。

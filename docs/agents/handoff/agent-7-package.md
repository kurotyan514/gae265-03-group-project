# 7 號 agent：打包追蹤與寄送

契約：`backend/app/contracts/package_agent.py`（`ClaimPackager`、`ClaimPackage`、`SendResult`）　假實作：`FakeClaimPackager`
先讀 [README.md](README.md)。

## 你的工作

所有待辦都完成後：

1. **整理送件包**（`build`）：信件主旨、內文、附件清單，使用者可以先預覽。
2. **寄出**（`send`）：使用者確認收件人後，用**使用者自己的 Gmail** 寄給保險業務員，並回傳寄送結果，之後可追蹤回覆。

平台在待辦沒有全部完成時會直接回 409，不會呼叫你的 `send`。

## 介面

```python
class ClaimPackager(Protocol):
    async def build(
        self,
        ctx: IncidentContext,
        google: GoogleAccess | None = None,  # v2.8 新增，選填
        user: UserContext | None = None,  # v2.8 新增，選填
    ) -> ClaimPackage: ...
    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: SendMode = "send",
    ) -> SendResult: ...
```

### 你拿到的

- `ctx`：完整事件快照——`facts`（事故經過）、`clauses`（適用保障）、`todos`、`documents`（含 `storage_path`，已存在使用者雲端）、`policy`（方案、保額、保險期間）。
- `recipient`：使用者確認過的收件信箱。
- `google.access_token(user, "gmail.send")`：使用者授權的 token。**目前平台還沒有保管授權，一律回傳 None**。

### 你交出的

`ClaimPackage`（build）：

| 欄位 | 說明 |
| --- | --- |
| `subject`、`body` | 主旨與內文 |
| `attachments[{document_id, file_name, storage_path}]` | 只能是 `ctx.documents` 裡 `recognition_status == "recognized"` 的文件 |
| `missing_todo_ids` | 還沒完成的待辦；有的話平台不允許送件 |
| `recipient_hint` | 建議收件人（保險公司理賠信箱等），由使用者確認 |
| `unavailable_attachments[{document_id, file_name, reason}]` | v2.8：預覽時在 Drive 上取不到（`not_found` 已刪除、`trashed` 在垃圾桶）、不會附在信裡的文件；送件頁用它提示使用者 |

`SendResult`（send）：`status`（`sent`／`drafted`／`failed`）、`external_ref`（寄出是 Gmail 郵件編號、建立草稿是草稿編號，寫進 `policy_submission.gmail_refs`）、`reason`、`gmail_url`（v2.12，選填：寄出是寄件備份那封信、建立草稿是那份草稿在 Gmail 網頁的連結，給畫面讓使用者點開）、`message_id`（v2.12，選填：Gmail 信件編號，草稿是草稿裡那封信的；平台存進 `gmail_refs`，理賠頁重新組連結用）。

**契約 v2.8（#155 驗收 7-2）**：平台的預覽與送件 API 呼叫 `build` 時帶上 `google` 與 `user`（只對簽名有這兩個參數的實作帶）。有 Drive 授權時確認附件還在不在：取不到的不附。同一項待辦已經重新上傳、有新的可附時，舊檔不附也不提示。沒有其他可附文件時：**需上傳的待辦列進 `missing_todo_ids`，平台就不讓寄出或建草稿**（一定要附的文件不能不處理）；不需上傳的才在信上的「未隨信附上的文件」寫待辦名稱加「（另行提供）」。信上不寫「請重新上傳」這類給使用者的話（信是寄給保險公司的）。`unavailable_attachments` 只列沒有其他可附文件的那幾份。沒授權或查不到時照舊全部附上。

**契約 v2.1（#151）**：`mode` 是 `"send"`（寄出，信裡還有空格就回 `failed`）或 `"draft"`（在使用者的 Gmail 建立草稿，有空格也能建、`recipient` 可以是 `None`）。平台把使用者填的空格放進 `package` 之後才呼叫；使用者選「自己處理、不建草稿」時不會呼叫你。平台只有建立草稿才帶 `mode`。

## 規則

1. 附件只能是辨識通過的文件。
2. 信件內容的金額、天數只能來自 `facts` 與 `ctx.policy`，LLM 不產生數字（ADR-0004）；LLM 若用來潤飾內文，必須用數字白名單檢查，失敗退回模板。
3. 沒有 Gmail 授權（token 是 None）：`send` 回 `failed`，`reason` 寫「請使用者先授權寄信」，**不要丟例外**，也不要寄出。
4. 內文含使用者的事故經過（可能含個資）：這是寄給保險公司的內容所以必須保留，但 **log 與錯誤訊息不放內容**；送進 LLM 前去識別化。
5. 信件結尾保留免責聲明：「實際能否理賠請以保險公司審核為準」。

## 待你和使用者決定的事

- 追蹤回覆（保險公司要求補件）要不要做、怎麼回到事件：規格 v3.3 不追蹤回信。資料表是 `policy_submission`（以保單為單位）：`status`（pending／drafted／sent／self_submitted）、`recipient`、`sent_at`、`gmail_refs`、`detail`。
- 收件人從哪來（設定檔、使用者輸入、保險公司資料表）。

## 驗收

- `CONTRACT_AGENT_7=<你的註冊名稱> make test args="-k contracts"` 全過。
- 自己補的測試：附件只含辨識通過的文件、缺待辦時 `missing_todo_ids` 正確、沒有授權時 `failed` 不丟例外、內文數字都在白名單內。

## 給你的 AI 助手

> 請依 `docs/agents/handoff/README.md` 的規則，實作 `ClaimPackager`（見 `backend/app/contracts/package_agent.py`）。先讀 `FakeClaimPackager`，再寫測試。Gmail 呼叫與 LLM 潤飾都包成可注入的函式，測試用假的且不連網；沒有授權時 send 回 failed 不丟例外；內文數字只來自 facts 與保單。實作放 `backend/app/agents/package/`，並在 `app/agents/registry.py` 用 `register_claim_packager` 註冊。

## 處理紀錄：PR #237

**處理日期：2026-11-07～2026-11-09**（各項後面的日期是完成那天）

7 號開發者在 [PR #237](https://github.com/kurotyan514/gae265-03-group-project/pull/237) 處理的事，給之後接手的人對照。細節見 [contract-changelog.md](contract-changelog.md) 2.8.0 那一筆與 `docs/specs/agent-7-package.md`。

**功能**
- 建立 Gmail 草稿（#154，2026-11-07）：`mode="draft"` 回 `drafted` 與草稿編號；有空格也能建，空格在草稿裡黃底紅字；收件者可以沒有；沒有 Gmail 或 Drive 授權回 `failed` 並說明要授權哪個。寄出與草稿用同一份主旨、內文與附件。
- 事故摘要的地點（#165，2026-11-07）：先用 `destination`，沒有才用 5 號記下的事實 `place`，都沒有或是「不知道」才留「（請填寫地點）」。
- 附件檔名重複時加「_序號」（#74，2026-11-07）。
- 取不到的附件（#155 驗收 7-2，2026-11-08）：Drive 的刪除是移到垃圾桶，在垃圾桶的也算取不到；寄出或建立草稿時每個附件都檢查完，一個檔案一行列出是哪些。
- 預覽時就確認附件還在不在 Drive（契約 v2.8.0，平台同意，2026-11-08～11-09）：`build` 多選填的 `google`、`user`，平台的預覽與送件 API 會帶上。同一項待辦已重新上傳的，舊檔不附也不提示；需上傳的文件取不到又沒有其他文件時，那項待辦列進 `missing_todo_ids`，平台就不讓寄出或建立草稿；不需上傳的才在信上寫「（另行提供）」。信上不寫給使用者的操作說明。
- 送件頁（`frontend/src/features/incident/SubmitPage.tsx`，平台負責的畫面，經使用者同意修改，2026-11-08～11-09）：失敗說明放在寄出按鈕旁並附連結；預覽時填的空格與收件者隨時暫存；取不到的附件用提示框列出，附「到 Google Drive 的垃圾桶還原」「到『上傳文件』重新上傳」與「重新檢查」。寄出時說明「處理好之前不能寄出」，從「我自己處理就好」建立草稿被擋下時說明「處理好之前不能建立草稿」。

**合併 main 時處理的衝突**（2026-11-08、2026-11-09）
- 契約版本號：開發期間 main 先後用掉 2.4.0（待辦的「適用」註記，#232）、2.5.0（`RuleRef.subsection`）、2.6.0（保障精確到「節」）、2.7.0（待辦帶出文件條件，#232），這次的變更排在後面改成 **2.8.0**；程式、測試、changelog 與文件裡指這次功能的版本號都跟著改，其他人的版本號不動。
- `contract-changelog.md`：兩邊都保留，依「新的寫在最上面」排成 2.8.0、2.7.0、2.6.0、2.5.0、2.4.0，7 號尚未實施的提案（多封信，暫緩）留在原位。
- 預覽與送件 API：保留 #232 交給 6、7 號前先濾掉不適用待辦的做法（`ctx.for_agents_6_7()`），再加上帶 Google 授權呼叫 `build`。
- 送件頁：main 把送件頁改成設計稿版型（#220），程式搬到 `SubmitPage.tsx`；7 號的修正改套到新版。
- `test_message_view.py` 的版本檢查改成「至少 2.3.0」，之後升版不用再改；`test_v2.py` 檢查目前版本是 2.8.0。
- `frontend/src/client/` 用 `make client` 重新產生。

**驗證**（2026-11-09）
- `make test`、`make lint` 全過；e2e `incident-flow`、`incident-submit` 全過（假 agent）。
- 用真的 Google 帳號手動驗收寄出、建立草稿、授權與 7-2（垃圾桶、永久刪除、還原、重新上傳、必要文件擋下寄出與建立草稿），結果在 #155。

**還沒做、交給平台**
- （agent_7_IMPL=gmail發信正常，可不用再測gmail-offline）`CONTRACT_AGENT_7=gmail-offline` 的契約整條流程測試寄出時沒帶 `fills`，在呼叫 7 號前就回 409；#154 改由真 Gmail 手動驗收代替，測試要平台修。
- 送件信空格的格式檢查（被保險人姓名、聯絡電話），要平台與前端做。
- `gmail.compose` 是受限 scope，正式上線前要送 Google 審核（#74）。
- 多封信暫緩，等有第二種事故類型或整張保單送件時再決定。

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

`SendResult`（send）：`status`（`sent`／`drafted`／`failed`）、`external_ref`（寄出是 Gmail 郵件編號、建立草稿是草稿編號，寫進 `policy_submission.gmail_refs`）、`reason`。

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

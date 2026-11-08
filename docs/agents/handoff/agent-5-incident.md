# 5 號 agent：事件釐清、問答、待辦

契約：`backend/app/contracts/incident_agent.py`（`IncidentAgent`、`IncidentReply`）　假實作：`FakeIncidentAgent`
畫面：2-2 描述事故、2-3 狀況總結、2-4 待辦清單、2-5 注意事項、2-6 後續問答。先讀 [README.md](README.md)。

## 你的工作

使用者出事後和你對話。你要：

1. 弄清楚事故是哪一類（事件類型），並依類型追問必要的細節。
2. 把釐清的事實整理成事件狀況（2-3）。
3. 判斷這次事故適用保單的哪些保障，並寫上理由。
4. 依情境補上基本待辦之外的待辦（例如被竊時加「向警方報案」）。
5. 回答使用者的問題，答案附條款出處。

## 介面

```python
class IncidentAgent(Protocol):
    async def start(
        self, ctx: IncidentContext, services: AgentServices
    ) -> IncidentReply: ...
    async def reply(
        self,
        ctx: IncidentContext,
        user_message: str,
        input_mode: InputMode,
        services: AgentServices,
    ) -> IncidentReply: ...
```

- `start`：平台剛建立事件時呼叫一次（`ctx.messages` 只有使用者的第一句描述）。通常回第一個追問。
- `reply`：使用者每說一句話呼叫一次；`ctx.messages` 已包含這句話之前的完整對話。`input_mode` 是 text／voice／quick_reply。

### 你拿到的（唯讀）

`IncidentContext`（`backend/app/contracts/common.py`），重點欄位：

| 欄位 | 說明 |
| --- | --- |
| `description` | 使用者的第一句描述（可能含個資） |
| `incident_type_code`／`incident_type_name` | 目前判斷的類型，還沒判斷出來是 None |
| `follow_up_questions` | 該類型預設的追問問題（類型未定時為空） |
| `policy` | 方案名稱、保額、保險期間、`insurance_codes`（只能查這些險種）、`coverages`（險種＋章，適用保障必須是其中之一） |
| `clauses` | 目前適用的保障（一開始是保單涵蓋的全部） |
| `facts`、`todos`、`documents`、`messages` | 目前已有的狀況、待辦（含 `status`：`pending`／`done`／`not_applicable`；`is_done` 保留，等於 `status == "done"`）、文件與對話 |

`AgentServices.search_rules(query, *, insurance_codes, k=5)`：在條款庫檢索，回傳 `RuleRef`（險種代碼、條號、章、標題、原文、頁碼）。`insurance_codes` 請傳 `ctx.policy.insurance_codes`。

### 你交出的

`IncidentReply`（欄位逐一說明，細節看契約檔的 docstring）：

| 欄位 | 平台怎麼處理 |
| --- | --- |
| `message` | 存成助手訊息 |
| `quick_replies` | 存在助手訊息上，前端顯示按鈕 |
| `citations[{insurance_code, article_no, score}]` | 驗證條文存在且屬於保單險種後存成出處 |
| `incident_type_code` | 必須是 `incident_type.code` 已有的值；改變時平台會把新類型的待辦範本補進來（不重複） |
| `title` | 事件標題（50 字內） |
| `facts[{fact_key, label, value, sort_order}]` | 依 `fact_key` 新增或覆蓋；`fact_key` 30 字內、`label` 20 字內 |
| `clauses[{insurance_code, section, reason}]` | **None = 不動；給列表 = 整組取代**。每一項必須在 `ctx.policy.coverages` 內 |
| `todos[{phase, title, note, template_id}]` | 只能新增（同階段同名稱的略過）；不能刪、不能改待辦的完成狀態（`status`／`is_done`）；`template_id` 必須屬於該事件類型的範本，自己加的填 None |
| `todo_applicability[{todo_id, applicable}]`（v2.4） | 註記待辦適不適用，只是 1/0，不改 `status`、不動已上傳的文件；沒列到的不動。`todo_id` 必須是這個事件自己的待辦（行程共用的 D10 不行，否則整則回覆被拒絕）。不適用的待辦對 6、7 號當作不存在；結論改回來就送 `applicable: true` |
| `finished` | 提示用，表示不會再問了；平台不存 |

範例（班機延誤釐清後）：

```json
{
  "message": "了解，班機延誤超過 6 小時。請先向航空公司索取延誤證明。",
  "quick_replies": ["已經拿到證明", "航空公司不給"],
  "citations": [{"insurance_code": "FUBON03", "article_no": 23}],
  "incident_type_code": "flight_delay",
  "facts": [{"fact_key": "delay_hours", "label": "延誤時間", "value": "6 小時"}],
  "clauses": [{"insurance_code": "FUBON03", "section": "第三章 班機延誤保險(定額給付-累進式)", "reason": "班機延誤"}],
  "todos": [{"phase": "on_site", "title": "向航空公司索取延誤證明"}],
  "finished": false
}
```

## 規則（違反會被平台擋下，回 502）

1. 類型代碼必須存在；適用保障必須在保單涵蓋內；出處必須是條款庫真的有、且屬於保單險種的條文。
2. 待辦只能新增，不能動既有待辦的完成狀態。
3. 回答中的數字（金額、天數、比例）只能來自保單或條款原文，不能由 LLM 產生。LLM 寫的文字要用白名單檢查數字（參考 `backend/app/domain/recommend/narrate.py` 的 `check_numbers`）。
4. 流程由程式決定：要追問哪個欄位、問幾次、何時結束由你的程式碼決定；LLM 最多額外提議 2 題追問（[ADR-0011](../../adr/0011-claim-flow-bounded-llm-judgement.md)）。
5. 送進 LLM 的使用者內容先去識別化（`backend/app/policy/deidentify.py`）。

## 驗收

- `CONTRACT_AGENT_5=<你的註冊名稱> make test args="-k contracts"` 全過（含「違反契約會被擋」與「整條流程」的測試）。
- 自己補的測試：以假 LLM 驗證——必問欄位都問過才結束、追問不超過 2 題、數字不在白名單時退回模板文字、引用的條文都來自檢索結果。
- 資料檔（事件類型的追問問題、待辦範本）由維護後台資料的成員提供；你可以用 `seed_sample_catalog` 的範例在本機試。

## 給你的 AI 助手

> 請依 `docs/agents/handoff/README.md` 的規則，實作 `IncidentAgent`（見 `backend/app/contracts/incident_agent.py`）。先讀 `FakeIncidentAgent` 了解輸出長相，再寫測試：用假 LLM（可注入的函式）驗證類型判斷、事實整理、保障收斂與待辦新增；檢索一律走 `services.search_rules`；回覆裡的出處只能是檢索結果。實作放 `backend/app/agents/incident/`，並在 `app/agents/registry.py` 註冊。

## 問答中修正描述（契約 2.4.0，#232）

問完之後，旅客在問答裡明確更正先前的答案（問句與假設不算），5 號更新狀況、需要時補問，然後重新下結論，用 `todo_applicability` 回報哪些待辦不適用或恢復。旅客在問答裡描述另一件新的事時，5 號不當問答回答，引導他按「有新狀況」，由前端用同一張保單開新事件。修正後新出現的待辦標「新增」，不再需要的標不適用（不做草稿與取消，Leon 11/08 討論）；問到一半的草稿與取消還沒做。

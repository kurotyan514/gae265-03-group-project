"""7 號 agent 的 ClaimPackager 實作。"""

import json
import re
from datetime import date
from pathlib import Path

from app.contracts import (
    AttachmentRef,
    ClaimPackage,
    DocumentView,
    IncidentContext,
    PolicySummary,
)

# 範本裡抓不到資料的格子一律留這幾個字，由使用者自己填；不猜、不用 LLM 補
TO_FILL = "（請填寫）"

# 方案資料（公司名稱的來源）。平台的預設位置是 backend/data/config；
# 平台可用環境變數 DATA_DIR 改位置，7 號不跟著改（目前沒有人設）。
# 檔案的位置或格式改了，tests/agents/package 的守門測試會失敗。
PLANS_FILE = Path(__file__).resolve().parents[3] / "data" / "config" / "plans.json"


def _can_attach(document: DocumentView) -> bool:
    """附件只取辨識通過、或使用者確認過的「不確定」文件（契約 v2.0）。

    沒有存檔位置的不算：寄信時要用 storage_path 向 Drive 取檔。
    """
    if not document.storage_path:
        return False
    return document.recognition_status == "recognized" or document.confirmed_by_user


def _period(policy: PolicySummary) -> str:
    """保險期間，例如 2026/08/10～08/14；跨年時迄日加上年份，例如 2026/12/30～2027/01/03。"""
    start, end = policy.start_date, policy.end_date
    if start is None or end is None:
        return TO_FILL
    end_format = "%m/%d" if end.year == start.year else "%Y/%m/%d"
    return f"{start:%Y/%m/%d}～{end:{end_format}}"


def _company(plan_id: str) -> str:
    """用方案 id 查方案資料的保險公司名稱；查不到留「（請填寫）」。

    檔案讀不到或格式不對時也留「（請填寫）」，不讓使用者看不到送件包
    （2026-11-05 7 號決定）；檔案的問題由守門測試在 CI 發現。
    """
    try:
        plans = json.loads(PLANS_FILE.read_text(encoding="utf-8"))["plans"]
        company = next((p.get("company") for p in plans if p["id"] == plan_id), None)
    except OSError, ValueError, KeyError, TypeError:
        return TO_FILL
    return company or TO_FILL


def _sum_insured(amount: int | None) -> str:
    """保額，例如 6000000 寫成「600 萬」、10000000 寫成「1000 萬」（依 7 號的範本與決定）。

    不是萬的整數倍時寫完整金額，不捨去（ADR-0004），例如「6,500,123 元」（7 號決定）。
    """
    if amount is None:
        return TO_FILL
    if amount % 10_000:
        return f"{amount:,} 元"
    return f"{amount // 10_000} 萬"  # 1000 萬不加逗號（7 號決定）


def _policy_section(policy: PolicySummary) -> str:
    return "\n".join(
        [
            "保單資訊",
            f"・公司：{_company(policy.plan_id)}",
            f"・方案：{policy.plan_name}",
            f"・保額：{_sum_insured(policy.sum_insured)}",
            f"・保險期間：{_period(policy)}",
            f"・保單號碼：{TO_FILL}",
        ]
    )


# 5 號記下的發生日期：代號是事故設定檔共用欄位的 date（backend/data/config/incident_catalog.json）
OCCURRED_DATE_KEY = "date"
_DATE = re.compile(r"^\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*$")


def _occurred_date(ctx: IncidentContext) -> str:
    """發生日期：看得懂就寫成 2026/08/10，看不懂照抄原文，沒有就留「（請填寫日期）」（7 號決定）。"""
    raw = next((f.value for f in ctx.facts if f.fact_key == OCCURRED_DATE_KEY), None)
    if not raw:
        return "（請填寫日期）"
    m = _DATE.match(raw)
    if m is None:
        return raw
    try:
        return f"{date(int(m[1]), int(m[2]), int(m[3])):%Y/%m/%d}"
    except ValueError:  # 格式像日期但不存在，例如 2026/13/45
        return raw


def _summary_section(ctx: IncidentContext) -> str:
    """事故摘要：各項分開、不組句子，使用者原話照原樣放（7 號決定）。"""
    incident_type = ctx.incident_type_name or "（請填寫事故類型）"
    place = ctx.destination or "（請填寫地點）"
    narrative = ctx.description if ctx.description.strip() else "（請填寫經過）"
    line = f"・{incident_type} · {_occurred_date(ctx)} · {place}：{narrative}"
    return "\n".join(["事故摘要", line])


def _greeting(has_attachments: bool) -> str:
    """開頭問候，依 7 號提供的範本；被保險人姓名平台沒有，留給使用者填。

    沒有附件時「相關文件如附件」不成立，改寫「相關文件另行提供」（7 號決定）。
    """
    documents = "相關文件如附件" if has_attachments else "相關文件另行提供"
    return (
        "您好：\n\n"
        f"我是被保險人{TO_FILL}，本次旅遊期間發生下列事故，依保單申請理賠，{documents}。"
    )


# 結尾的聯絡電話與補件說明，依 7 號提供的範本；電話平台沒有，留給使用者填
CLOSING = f"聯絡電話：{TO_FILL}\n如需補件，請直接回覆此信。"
# 免責聲明（交接說明規則 5），放在信件最後
DISCLAIMER = "實際能否理賠請以保險公司審核為準"


def _subject(ctx: IncidentContext) -> str:
    """主旨只放方案名稱與保險期間（方案名稱已含公司簡稱）。

    主旨抓不到資料時寫明是哪一項（7 號決定）；內文仍用「（請填寫）」。
    """
    period = _period(ctx.policy)
    if period == TO_FILL:
        period = "（請填寫保險期間）"
    return f"旅遊保險理賠申請－{ctx.policy.plan_name}－{period}"


def _attachment_documents(ctx: IncidentContext) -> list[DocumentView]:
    """可以當附件的文件。

    只寄待辦清單要求的文件：對不到待辦的（使用者多傳的）不寄。
    依待辦順序排，不是上傳順序；整張保單共用的待辦（理賠申請書 D10）的文件排最後，
    依 7 號的範本。
    """
    todos = {t.id: t for t in ctx.todos}
    pairs = [
        (todos[d.todo_id], d)
        for d in ctx.documents
        if d.todo_id is not None and d.todo_id in todos and _can_attach(d)
    ]
    # 先事件的待辦、後 D10；同一類依待辦順序；同一項待辦的多份文件維持上傳順序
    pairs.sort(key=lambda pair: (pair[0].scope == "policy", pair[0].sort_order))
    return [d for _, d in pairs]


def _without_document_section(ctx: IncidentContext) -> str | None:
    """使用者自行勾選、沒附文件的待辦（7 號決定）；沒有這種待辦時不出現。

    寫待辦名稱加「（另行提供）」，順序同附件：依待辦順序，理賠申請書 D10 放最後。
    """
    todos = sorted(
        (t for t in ctx.todos if t.status == "done" and t.without_document),
        key=lambda t: (t.scope == "policy", t.sort_order),
    )
    if not todos:
        return None
    return "\n".join(["未隨信附上的文件", *(f"・{t.title}（另行提供）" for t in todos)])


def _attachment_section(attachments: list[AttachmentRef]) -> str:
    """附件清單：一個檔案一行，與實際附件同一份資料、同一個順序（依 7 號的範本）。

    沒有附件時寫「・（無）」（7 號決定）。
    """
    lines = [f"・{a.file_name}" for a in attachments] or ["・（無）"]
    return "\n".join(["附件清單", *lines])


class GmailClaimPackager:
    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        attachments = [
            AttachmentRef(
                document_id=d.id, file_name=d.file_name, storage_path=d.storage_path
            )
            for d in _attachment_documents(ctx)
        ]
        sections = [
            _greeting(bool(attachments)),
            _policy_section(ctx.policy),
            _summary_section(ctx),
            _without_document_section(ctx),
            _attachment_section(attachments),
            CLOSING,
            DISCLAIMER,
        ]
        return ClaimPackage(
            subject=_subject(ctx),
            body="\n\n".join(s for s in sections if s),
            attachments=attachments,
            # 還沒做的待辦；「不適用」不算缺漏，使用者自行勾選、未附文件的算完成
            missing_todo_ids=[t.id for t in ctx.todos if t.status == "pending"],
        )

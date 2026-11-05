"""7 號 agent 的 ClaimPackager 實作。"""

import json
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


def _subject(ctx: IncidentContext) -> str:
    """主旨只放方案名稱與保險期間（方案名稱已含公司簡稱）。"""
    return f"旅遊保險理賠申請－{ctx.policy.plan_name}－{_period(ctx.policy)}"


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


class GmailClaimPackager:
    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        return ClaimPackage(
            subject=_subject(ctx),
            body=_policy_section(ctx.policy),
            attachments=[
                AttachmentRef(
                    document_id=d.id, file_name=d.file_name, storage_path=d.storage_path
                )
                for d in _attachment_documents(ctx)
            ],
            # 還沒做的待辦；「不適用」不算缺漏，使用者自行勾選、未附文件的算完成
            missing_todo_ids=[t.id for t in ctx.todos if t.status == "pending"],
        )

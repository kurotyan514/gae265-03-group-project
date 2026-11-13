"""7 號 agent 的 ClaimPackager 實作。"""

import html
import json
import re
import uuid
from datetime import date
from email import policy
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

from app.agents.package.google_api import (
    DriveFile,
    DriveFileStatus,
    GoogleApi,
    GoogleApiError,
    GoogleErrorKind,
)
from app.contracts import (
    AttachmentRef,
    ClaimPackage,
    DocumentView,
    GoogleAccess,
    IncidentContext,
    PolicySummary,
    SendMode,
    SendResult,
    UnavailableAttachment,
    UserContext,
)


def _to_fill(item: str) -> str:
    """抓不到資料的空格，固定寫成「（請填寫＋項目）」，由使用者自己填；不猜、不用 LLM 補。

    前端靠這個固定寫法找出要填的項目（2026-11-06 7 號決定），要改寫法得先跟前端說。
    """
    return f"（請填寫{item}）"


_BLANK = re.compile(r"（請填寫([^）]+)）")


def _blank_items(*texts: str) -> list[str]:
    """信裡還要填的項目，照出現的順序，重複的只列一次。"""
    items: list[str] = []
    for text in texts:
        for item in _BLANK.findall(text):
            if item not in items:
                items.append(item)
    return items


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
        return _to_fill("保險期間")
    end_format = "%m/%d" if end.year == start.year else "%Y/%m/%d"
    return f"{start:%Y/%m/%d}～{end:{end_format}}"


def _company(plan_id: str) -> str:
    """用方案 id 查方案資料的保險公司名稱；查不到留「（請填寫保險公司）」。

    檔案讀不到或格式不對時也一樣，不讓使用者看不到送件包
    （2026-11-05 7 號決定）；檔案的問題由守門測試在 CI 發現。
    """
    try:
        plans = json.loads(PLANS_FILE.read_text(encoding="utf-8"))["plans"]
        company = next((p.get("company") for p in plans if p["id"] == plan_id), None)
    except OSError, ValueError, KeyError, TypeError:
        return _to_fill("保險公司")
    return company or _to_fill("保險公司")


def _sum_insured(amount: int | None) -> str:
    """保額，例如 6000000 寫成「600 萬」、10000000 寫成「1000 萬」（依 7 號的範本與決定）。

    不是萬的整數倍時寫完整金額，不捨去（ADR-0004），例如「6,500,123 元」（7 號決定）。
    """
    if amount is None:
        return _to_fill("保額")
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
            f"・保單號碼：{_to_fill('保單號碼')}",
        ]
    )


# 5 號記下的發生日期：代號是事故設定檔共用欄位的 date（backend/data/config/incident_catalog.json）
OCCURRED_DATE_KEY = "date"
# 能換算的寫法：2026/8/10、2026-8-10、2026年8月10日（一定要有年份，7 號不猜年份）
_DATE = re.compile(
    r"^\s*(\d{4})(?:[/-](\d{1,2})[/-](\d{1,2})|年(\d{1,2})月(\d{1,2})日)\s*$"
)
DATE_TO_FILL = _to_fill("日期")


def _occurred_date(ctx: IncidentContext) -> str:
    """發生日期：能換算成真實日期就寫成 2026/08/10，其他一律留「（請填寫日期）」（7 號決定）。

    例如 5 號問不到時存的「不知道」、不存在的「2026/13/45」、沒有年份的「8月10日」。
    """
    raw = next((f.value for f in ctx.facts if f.fact_key == OCCURRED_DATE_KEY), None)
    m = _DATE.match(raw or "")
    if m is None:
        return DATE_TO_FILL
    month, day = (m[2], m[3]) if m[2] else (m[4], m[5])
    try:
        return f"{date(int(m[1]), int(month), int(day)):%Y/%m/%d}"
    except ValueError:  # 格式像日期但不存在，例如 2026/13/45
        return DATE_TO_FILL


# 5 號記下的發生地點：代號是事故設定檔共用欄位的 place
OCCURRED_PLACE_KEY = "place"
# 5 號問不到時存的值（backend/app/agents/incident/agent.py 的 UNKNOWN），不能當地點寫進信
_UNKNOWN_FACT = "不知道"


def _place(ctx: IncidentContext) -> str:
    """地點：先用建立事件時填的目的地，沒有才用 5 號記下的發生地點（#165）。

    兩個都沒有、或發生地點是「不知道」時留「（請填寫地點）」。
    """
    if ctx.destination and ctx.destination.strip():
        return ctx.destination.strip()
    raw = next((f.value for f in ctx.facts if f.fact_key == OCCURRED_PLACE_KEY), "")
    place = raw.strip()
    if not place or place.startswith(_UNKNOWN_FACT):
        return _to_fill("地點")
    return place


def _summary_section(ctx: IncidentContext) -> str:
    """事故摘要：各項分開、不組句子，使用者原話照原樣放（7 號決定）。"""
    incident_type = ctx.incident_type_name or _to_fill("事故類型")
    place = _place(ctx)
    narrative = ctx.description if ctx.description.strip() else _to_fill("經過")
    line = f"・{incident_type} · {_occurred_date(ctx)} · {place}：{narrative}"
    return "\n".join(["事故摘要", line])


def _greeting(has_attachments: bool) -> str:
    """開頭問候，依 7 號提供的範本；被保險人姓名平台沒有，留給使用者填。

    沒有附件時「相關文件如附件」不成立，改寫「相關文件另行提供」（7 號決定）。
    """
    documents = "相關文件如附件" if has_attachments else "相關文件另行提供"
    return (
        "您好：\n\n"
        f"我是被保險人{_to_fill('被保險人姓名')}，本次旅遊期間發生下列事故，依保單申請理賠，{documents}。"
    )


# 結尾的聯絡電話與補件說明，依 7 號提供的範本；電話平台沒有，留給使用者填
CLOSING = f"聯絡電話：{_to_fill('聯絡電話')}\n如需補件，請直接回覆此信。"
# 免責聲明（交接說明規則 5），放在信件最後
DISCLAIMER = "實際能否理賠請以保險公司審核為準"


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


def _without_document_section(
    ctx: IncidentContext, unattached: frozenset[uuid.UUID] = frozenset()
) -> str | None:
    """沒有隨信附上文件的待辦；沒有這種待辦時不出現。

    包含使用者自行勾選、沒附文件的（7 號決定），以及文件在 Drive 上取不到、又沒有其他可附文件的
    （`unattached`，契約 v2.8）。寫待辦名稱加「（另行提供）」，不寫「請重新上傳」這類給使用者的話：
    這封信是寄給保險公司的（2026-11-08 決定）。順序同附件：依待辦順序，理賠申請書 D10 放最後。
    """
    todos = sorted(
        (
            t
            for t in ctx.todos
            if t.status == "done" and (t.without_document or t.id in unattached)
        ),
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


GMAIL_SCOPE = "gmail.compose"
DRIVE_SCOPE = "drive.file"

_DRIVE_ERRORS: dict[GoogleErrorKind, str] = {
    "unauthorized": "Google Drive 的授權已失效，請重新授權 Google Drive",
}


def _missing_reason(not_found: list[str], trashed: list[str]) -> str:
    """取不到的附件：一句說明加上一個檔案一行（「・檔名」），看得出有幾個（7-2）。

    檔名是系統取的、不含個資（ADR-0021），可以放進 reason。垃圾桶裡的請使用者還原；
    永久刪除的請重新上傳。兩種都有時兩段都列，段與段之間也是換行。
    送件頁照換行顯示，「垃圾桶」「重新上傳」是給前端附連結的固定說法。
    """
    lines: list[str] = []
    if not_found:
        lines.append(f"Google Drive 上找不到下面 {len(not_found)} 個附件，請重新上傳：")
        lines += [f"・{name}" for name in not_found]
    if trashed:
        lines.append(
            f"下面 {len(trashed)} 個附件在 Google Drive 的垃圾桶裡，"
            "請到 Google Drive 的垃圾桶還原後再試一次："
        )
        lines += [f"・{name}" for name in trashed]
    return "\n".join(lines)


_GMAIL_ERRORS: dict[GoogleErrorKind, str] = {
    "unauthorized": "Gmail 的授權已失效，請重新授權 Gmail",
}
# 其他錯誤（含暫時連不上）依這次要做的事說明沒做成什麼
_UNAVAILABLE: dict[SendMode, str] = {
    "send": "暫時連不上 Google，沒有寄出，請稍後再試",
    "draft": "暫時連不上 Google，沒有建立草稿，請稍後再試",
}
# 平台沒給 Google 轉接器（只做預覽時）
_NOT_READY: dict[SendMode, str] = {
    "send": "寄送功能開發中，尚未寄出",
    "draft": "建立草稿功能開發中，尚未建立",
}

# 草稿的帶顏色版本：每個「（請填寫＋項目）」用黃底紅字標出（規格「寄送」2026-11-06 決定）
_BLANK_STYLE = "background-color:#ffff00;color:#d00000;font-weight:bold"


def _highlighted_html(body: str) -> str:
    """內文的 HTML 版本：先整段跳脫，再把空格包上醒目的樣式；換行與空白照原樣保留。"""
    escaped = html.escape(body, quote=False)
    marked = _BLANK.sub(
        lambda m: f'<span style="{_BLANK_STYLE}">{m[0]}</span>', escaped
    )
    return f'<div style="white-space:pre-wrap">{marked}</div>'


def _unique_names(names: list[str]) -> list[str]:
    """附件檔名不重名（#74）：重複的從第二個起在副檔名前加「_序號」，例如 理賠申請書_1_2.pdf。"""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        candidate, n = name, 1
        while candidate in seen:
            n += 1
            stem, dot, suffix = name.rpartition(".")
            candidate = f"{stem}_{n}.{suffix}" if dot and stem else f"{name}_{n}"
        seen.add(candidate)
        result.append(candidate)
    return result


def _message(
    sender: str,
    recipient: str | None,
    package: ClaimPackage,
    files: list[DriveFile],
    *,
    highlight_blanks: bool = False,
) -> bytes:
    """組成要寄出或存成草稿的信：寄出與草稿用同一份主旨、內文與附件（#154）。

    純文字內文照送件包原樣；草稿另外加一份把空格標出來的 HTML 版本。
    附件的類型與內容取自 Drive，檔名用 Drive 上的名字、重名時加序號。
    收件者是空的（草稿）時不帶 To，使用者到 Gmail 再填。
    """
    message = EmailMessage()
    message["From"] = sender
    if recipient:
        message["To"] = recipient
    message["Subject"] = package.subject
    message.set_content(package.body)
    if highlight_blanks:
        message.add_alternative(_highlighted_html(package.body), subtype="html")
    for file, name in zip(files, _unique_names([f.name for f in files]), strict=True):
        maintype, _, subtype = file.mime_type.partition("/")
        message.add_attachment(
            file.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=name,
        )
    return message.as_bytes(policy=policy.SMTP)


class GmailClaimPackager:
    def __init__(self, google_api: GoogleApi | None = None) -> None:
        # 平台用 factory 建立時一定會給（正式版或離線版）；只做送件包預覽時可以不給，
        # 這時 send 回「開發中」，什麼都不寄
        self.google_api = google_api

    async def build(
        self,
        ctx: IncidentContext,
        google: GoogleAccess | None = None,
        user: UserContext | None = None,
    ) -> ClaimPackage:
        documents = _attachment_documents(ctx)
        # 契約 v2.8：有 Drive 授權時先確認附件還在不在；取不到的不附在信裡（#155 驗收 7-2）
        unavailable = await self._unavailable(documents, google, user)
        available = [d for d in documents if d.id not in unavailable]
        attached_todos = {d.todo_id for d in available}
        # 同一項待辦已經重新上傳、有新的可附時，舊檔不附、也不提示（2026-11-08 決定）；
        # 沒有其他可附文件的才要處理
        lost = [
            d
            for d in documents
            if d.id in unavailable and d.todo_id not in attached_todos
        ]
        todos = {t.id: t for t in ctx.todos}
        lost_todo_ids = {d.todo_id for d in lost if d.todo_id in todos}
        # 需上傳的一定要處理，不能寄出：列為還缺的待辦，平台就會擋下（2026-11-08 決定）；
        # 不需上傳的，信上寫另行提供
        blocking = {
            i for i in lost_todo_ids if i is not None and todos[i].requires_upload
        }
        unattached = frozenset(
            i for i in lost_todo_ids if i is not None and i not in blocking
        )
        attachments = [
            AttachmentRef(
                document_id=d.id, file_name=d.file_name, storage_path=d.storage_path
            )
            for d in available
        ]
        sections = [
            _greeting(bool(attachments)),
            _policy_section(ctx.policy),
            _summary_section(ctx),
            _without_document_section(ctx, unattached),
            _attachment_section(attachments),
            CLOSING,
            DISCLAIMER,
        ]
        return ClaimPackage(
            subject=_subject(ctx),
            body="\n\n".join(s for s in sections if s),
            attachments=attachments,
            # 還沒做的待辦；「不適用」不算缺漏，使用者自行勾選、未附文件的算完成。
            # 需上傳、文件卻在 Drive 上取不到的也算還缺（契約 v2.8）
            missing_todo_ids=[
                t.id for t in ctx.todos if t.status == "pending" or t.id in blocking
            ],
            unavailable_attachments=[
                UnavailableAttachment(
                    document_id=d.id, file_name=d.file_name, reason=unavailable[d.id]
                )
                for d in lost
            ],
        )

    async def _unavailable(
        self,
        documents: list[DocumentView],
        google: GoogleAccess | None,
        user: UserContext | None,
    ) -> dict[uuid.UUID, Literal["not_found", "trashed"]]:
        """Drive 上取不到的文件：文件編號 → 找不到或在垃圾桶。

        沒有轉接器、沒給授權、沒有 Drive 授權時不檢查；授權失效或暫時連不上時不確定檔案在不在，
        不能因此少附，當作都還在（寄出時 send 會再檢查一次）。只讀檔案資訊，不下載內容。
        """
        api = self.google_api
        if api is None or google is None or user is None or not documents:
            return {}
        token = await google.access_token(user, DRIVE_SCOPE)
        if token is None:
            return {}
        result: dict[uuid.UUID, Literal["not_found", "trashed"]] = {}
        try:
            for document in documents:
                status: DriveFileStatus = await api.file_status(
                    token, document.storage_path
                )
                if status != "ok":
                    result[document.id] = status
        except GoogleApiError:
            return {}
        return result

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: SendMode = "send",
    ) -> SendResult:
        # 契約 v2.1 的 mode："send" 寄出、"draft" 在使用者的 Gmail 建立草稿（#154）。
        # 兩者用同一份信件內容與附件，差別只在：寄出要有收件者、不能有空格；
        # 草稿可以沒有收件者、可以有空格（空格在帶顏色的版本標出來）
        if mode == "send" and not recipient:
            return SendResult(status="failed", reason="要有收件者才能寄出")
        # 寄信用 Gmail、附件從使用者的 Drive 取（ADR-0020），草稿也一樣。沒有附件就不用 Drive 授權：
        # 使用者可能沒上傳文件、也沒授權 Drive。
        # 沒有授權時回 failed 說明要授權哪個，不丟例外、不寄出也不建草稿（交接說明規則 3）
        gmail_token = await google.access_token(user, GMAIL_SCOPE)
        drive_token = (
            await google.access_token(user, DRIVE_SCOPE) if package.attachments else ""
        )
        if gmail_token is None or drive_token is None:
            missing = [
                name
                for token, name in (
                    (gmail_token, "Gmail"),
                    (drive_token, "Google Drive"),
                )
                if token is None
            ]
            return SendResult(
                status="failed", reason=f"請先授權 {'、'.join(missing)}，才能送件"
            )
        # 有空格的信不能寄出；前端與平台都會先擋，這是最後一道防線（規格「寄送」）
        if mode == "send":
            blanks = _blank_items(package.subject, package.body)
            if blanks:
                return SendResult(
                    status="failed",
                    reason=f"信裡還有要填寫的項目：{'、'.join(blanks)}，填完才能寄出",
                )
        api = self.google_api
        if api is None:
            return SendResult(status="failed", reason=_NOT_READY[mode])
        # 先取完所有附件才寄或建草稿：任一個取不到就什麼都不做（規格「寄送」）。
        # 找不到或在垃圾桶的每個都檢查完再一起列出（7-2）；授權失效、連不上就直接停
        files: list[DriveFile] = []
        not_found: list[str] = []
        trashed: list[str] = []
        for attachment in package.attachments:
            try:
                files.append(await api.fetch_file(drive_token, attachment.storage_path))
            except GoogleApiError as error:
                if error.kind == "not_found":
                    not_found.append(attachment.file_name)
                elif error.kind == "trashed":
                    trashed.append(attachment.file_name)
                else:
                    return SendResult(
                        status="failed", reason=_reason(error, _DRIVE_ERRORS, mode)
                    )
        if not_found or trashed:
            return SendResult(
                status="failed", reason=_missing_reason(not_found, trashed)
            )
        message = _message(
            user.email, recipient, package, files, highlight_blanks=mode == "draft"
        )
        try:
            if mode == "draft":
                draft_id = await api.create_draft(gmail_token, message)
                return SendResult(status="drafted", external_ref=draft_id)
            message_id = await api.send_message(gmail_token, message)
        except GoogleApiError as error:
            return SendResult(
                status="failed", reason=_reason(error, _GMAIL_ERRORS, mode)
            )
        return SendResult(status="sent", external_ref=message_id)


def _reason(
    error: GoogleApiError, known: dict[GoogleErrorKind, str], mode: SendMode
) -> str:
    """Google 錯誤的說明：只放錯誤類別，不放信件內容、token 或 email（ADR-0009）。"""
    return known.get(error.kind, _UNAVAILABLE[mode])

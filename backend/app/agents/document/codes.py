"""文件代碼（理賠文件規則，`incident_catalog.json`）與 6 號認得的文件種類。

第一批只做班機延誤：D01 延誤／取消證明、D02 機票與登機證（或搭機證明）、D10 理賠申請書。
第二批是海外就醫（#233，泰國醫療 demo）：D13 診斷書、D14 醫療費用收據、D24 受益人身分證明（身分證、護照）。
種類由程式依關鍵字判斷（ADR-0004、ADR-0011）；`document_kind` 寫成「D02 登機證」，
前半是文件代碼、後半是種類名稱，同一項待辦的其他文件也從這裡讀回種類。
"""

import re
from dataclasses import dataclass

from app.contracts import DocumentView, TodoView


@dataclass(frozen=True)
class Part:
    """一種文件。一個文件代碼可以有好幾種（D02 有機票、登機證、搭機證明）。"""

    key: str
    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DocumentSpec:
    code: str
    name: str
    parts: tuple[Part, ...]
    # 待辦還沒有 document_code 前（#71），用待辦標題的關鍵字對應
    todo_keywords: tuple[str, ...]

    def part(self, key: str) -> Part:
        return next(p for p in self.parts if p.key == key)


SPECS: dict[str, DocumentSpec] = {
    s.code: s
    for s in (
        DocumentSpec(
            code="D01",
            name="延誤／取消證明",
            parts=(
                Part(
                    "delay_certificate",
                    "延誤／取消證明",
                    (
                        "延誤證明",
                        "延遲證明",
                        "取消證明",
                        "班機延誤",
                        "航班延誤",
                        "delay certificate",
                        "flight delay",
                        "delay confirmation",
                        "cancellation certificate",
                        "遅延証明",
                        "欠航証明",
                    ),
                ),
            ),
            todo_keywords=("延誤", "取消證明"),
        ),
        DocumentSpec(
            code="D02",
            name="機票與登機證",
            parts=(
                Part(
                    "ticket",
                    "機票",
                    (
                        "電子機票",
                        "機票",
                        "e-ticket",
                        "eticket",
                        "ticket number",
                        "itinerary receipt",
                        "行程表",
                        "航空券",
                    ),
                ),
                Part("boarding_pass", "登機證", ("登機證", "boarding pass", "搭乗券")),
                # 合併種類由兩種文件的標題共同判定，不靠單一關鍵字。
                Part("ticket_boarding", "機票及登機證", ()),
                Part(
                    "boarding_proof",
                    "搭機證明",
                    (
                        "搭機證明",
                        "搭乘證明",
                        "certificate of boarding",
                        "boarding certificate",
                        "搭乗証明",
                    ),
                ),
            ),
            todo_keywords=("機票", "登機證", "搭機證明"),
        ),
        DocumentSpec(
            code="D10",
            name="理賠申請書",
            parts=(
                Part(
                    "claim_form",
                    "理賠申請書",
                    ("理賠申請書", "保險金申請書", "申請書", "claim form"),
                ),
            ),
            todo_keywords=("申請書",),
        ),
        DocumentSpec(
            code="D13",
            name="診斷書",
            parts=(
                Part(
                    "diagnosis_certificate",
                    "診斷書",
                    (
                        "診斷書",
                        "診斷證明",
                        "medical certificate",
                        "certificate of diagnosis",
                        "medical report",
                        "ใบรับรองแพทย์",
                        "診断書",
                    ),
                ),
            ),
            todo_keywords=("診斷書",),
        ),
        DocumentSpec(
            code="D14",
            name="醫療費用收據",
            parts=(
                Part(
                    "medical_receipt",
                    "醫療費用收據",
                    # 「收據」「receipt」很常見（機票、便利商店也有），要同時看得到醫療字眼才算，
                    # 見 keyword_hits 的 _MEDICAL_CONTEXT。
                    ("收據", "receipt", "ใบเสร็จรับเงิน", "領収書", "領収証"),
                ),
            ),
            todo_keywords=("醫療費用收據", "醫療收據"),
        ),
        DocumentSpec(
            code="D24",
            name="受益人身分證明",
            parts=(
                # 護照不用「passport」當關鍵字：診斷書、收據上也常印「Passport No.」。
                # 護照資料頁一定有機讀碼（P<TWN…），見 keyword_hits 的 _PASSPORT_MRZ。
                Part(
                    "identity",
                    "身分證明",
                    ("國民身分證", "居留證", "resident certificate"),
                ),
            ),
            todo_keywords=("身分證明",),
        ),
    )
}


@dataclass(frozen=True)
class Kind:
    code: str
    part: str

    @property
    def label(self) -> str:
        return SPECS[self.code].part(self.part).label

    @property
    def document_kind(self) -> str:
        return f"{self.code} {self.label}"


def parse_kind(document_kind: str | None) -> Kind | None:
    """把「D02 登機證」讀回種類；不是 6 號寫的格式就回 None。"""
    if not document_kind or " " not in document_kind:
        return None
    code, label = document_kind.split(" ", 1)
    spec = SPECS.get(code)
    if spec is None:
        return None
    part = next((p for p in spec.parts if p.label == label), None)
    return Kind(code, part.key) if part else None


# 行李延誤不在第一批範圍；不能因共用「延誤證明」字樣而對到班機延誤的 D01。
# 只排除明確的行李延誤描述，單純提到行李額度等資訊不影響班機證明。
_BAGGAGE_DELAY = re.compile(
    r"行李\s*(?:延誤|延遲|遲延)|(?:手荷物|荷物)\s*遅延|"
    r"\b(?:baggage|luggage)\s+delay(?:ed)?\b|"
    r"\bdelayed\s+(?:baggage|luggage)\b",
    re.IGNORECASE,
)

# 醫療費用收據要看得到看診的字眼；只有「收據／receipt」的機票、便利商店、飯店收據不算。
_MEDICAL_CONTEXT = re.compile(
    r"醫療|醫院|診所|門診|急診|診察|診療|藥費|"
    r"\b(?:medical|hospital|clinic|consultation|doctor|physician|pharmacy|medicine)\b|"
    r"โรงพยาบาล|คลินิก|病院|医療",
    re.IGNORECASE,
)

# 護照資料頁的機讀碼第一行：P、類別（< 或一個字母）、三碼國別，接著姓<<名
_PASSPORT_MRZ = re.compile(r"P[A-Z<][A-Z]{3}[A-Z]+<<[A-Z<]+")

_TICKET_HEADING = re.compile(
    r"^\s*(?:(?:電子)?機票(?!\s*(?:號碼|編號))|"
    r"e-?ticket\b(?!\s*(?:number\b|no\b|#))|itinerary receipt\b|航空券)",
    re.IGNORECASE | re.MULTILINE,
)
_BOARDING_HEADING = re.compile(
    r"^\s*(?:登機證|boarding pass\b|搭乗券)", re.IGNORECASE | re.MULTILINE
)
_COMBINED_HEADING = re.compile(
    r"^\s*(?:(?:電子)?機票\s*[暨及與和／/]\s*登機證|"
    r"e-?ticket\s*(?:&|and|/)\s*boarding pass\b|航空券\s*[・／/]\s*搭乗券)",
    re.IGNORECASE | re.MULTILINE,
)


def keyword_hits(text: str) -> dict[Kind, dict[str, int]]:
    """每種文件的關鍵字各出現幾次（不分大小寫）；沒命中的種類不列。"""
    lowered = text.lower()
    hits: dict[Kind, dict[str, int]] = {}
    for spec in SPECS.values():
        if spec.code == "D01" and _BAGGAGE_DELAY.search(text):
            continue
        if spec.code == "D14" and not _MEDICAL_CONTEXT.search(text):
            continue
        for part in spec.parts:
            counts = {k: lowered.count(k.lower()) for k in part.keywords}
            counts = {k: n for k, n in counts.items() if n}
            if counts:
                hits[Kind(spec.code, part.key)] = counts
    mrz = len(_PASSPORT_MRZ.findall(text.replace(" ", "")))
    if mrz:
        hits.setdefault(Kind("D24", "identity"), {})["護照機讀碼"] = mrz
    ticket, boarding = Kind("D02", "ticket"), Kind("D02", "boarding_pass")
    if (
        ticket in hits
        and boarding in hits
        and Kind("D02", "boarding_proof") not in hits
    ):
        # 票號也會印在單獨的登機證上，不能只因為有 Ticket Number 就當成兩種文件。
        combined = _COMBINED_HEADING.search(text) or (
            _TICKET_HEADING.search(text) and _BOARDING_HEADING.search(text)
        )
        if combined:
            hits[Kind("D02", "ticket_boarding")] = hits.pop(ticket) | hits.pop(boarding)
        elif not _TICKET_HEADING.search(text):
            hits.pop(ticket)
    return hits


def classify(text: str) -> list[Kind]:
    """依關鍵字找出文件種類。回傳得分最高的種類；同分就全部回傳，由呼叫端當成「不確定」。

    得分是關鍵字出現的總次數（`keyword_hits`）。搭機證明的關鍵字比登機證更具體，命中時以搭機證明為準。
    """
    scores = {kind: sum(c.values()) for kind, c in keyword_hits(text).items()}
    combined = Kind("D02", "ticket_boarding")
    if combined in scores and any(k.code != "D02" for k in scores):
        return list(scores)  # 混入別種文件代碼時仍交給使用者確認，不因合併加分而蓋過。
    proof = Kind("D02", "boarding_proof")
    if proof in scores:
        scores.pop(Kind("D02", "boarding_pass"), None)
    if not scores:
        return []
    best = max(scores.values())
    return [k for k, s in scores.items() if s == best]


def matching_todos(code: str, todos: list[TodoView]) -> list[TodoView]:
    """用文件代碼找待辦；平台的 TodoView 還沒有 document_code 時，用標題關鍵字暫代。"""
    spec = SPECS[code]
    found = []
    for todo in todos:
        if todo.status == "not_applicable":
            continue
        todo_code = getattr(todo, "document_code", None)
        if todo_code is not None:
            if todo_code == code:
                found.append(todo)
        elif any(k in todo.title for k in spec.todo_keywords):
            found.append(todo)
    return found


def completion(
    kind: Kind, todo: TodoView, documents: list[DocumentView]
) -> tuple[bool, str | None]:
    """這份文件加上同一項待辦已通過的文件，待辦是否完成；沒完成時回補件提醒。

    D02：機票和登機證都到（可同一份），或一份搭機證明，才算完成。其他文件一份就完成。
    """
    if kind.code != "D02":
        return True, None
    have = {kind.part}
    for d in documents:
        if d.todo_id == todo.id and d.recognition_status == "recognized":
            other = parse_kind(d.document_kind)
            if other and other.code == "D02":
                have.add(other.part)
    if {"boarding_proof", "ticket_boarding"} & have or {
        "ticket",
        "boarding_pass",
    } <= have:
        return True, None
    missing = "登機證" if "ticket" in have else "機票"
    return False, f"已收到，還缺{missing}（或改傳一份搭機證明）"

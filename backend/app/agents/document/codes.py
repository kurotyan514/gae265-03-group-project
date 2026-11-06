"""文件代碼（理賠文件規則，`incident_catalog.json`）與 6 號認得的文件種類。

第一批只做班機延誤：D01 延誤／取消證明、D02 機票與登機證（或搭機證明）、D10 理賠申請書。
種類由程式依關鍵字判斷（ADR-0004、ADR-0011）；`document_kind` 寫成「D02 登機證」，
前半是文件代碼、後半是種類名稱，同一項待辦的其他文件也從這裡讀回種類。
"""

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


def keyword_hits(text: str) -> dict[Kind, dict[str, int]]:
    """每種文件的關鍵字各出現幾次（不分大小寫）；沒命中的種類不列。"""
    lowered = text.lower()
    hits: dict[Kind, dict[str, int]] = {}
    for spec in SPECS.values():
        for part in spec.parts:
            counts = {k: lowered.count(k.lower()) for k in part.keywords}
            counts = {k: n for k, n in counts.items() if n}
            if counts:
                hits[Kind(spec.code, part.key)] = counts
    return hits


def classify(text: str) -> list[Kind]:
    """依關鍵字找出文件種類。回傳得分最高的種類；同分就全部回傳，由呼叫端當成「不確定」。

    得分是關鍵字出現的總次數（`keyword_hits`）。搭機證明的關鍵字比登機證更具體，命中時以搭機證明為準。
    """
    scores = {kind: sum(c.values()) for kind, c in keyword_hits(text).items()}
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

    D02：機票和登機證兩份都到，或一份搭機證明，才算完成。其他文件一份就完成。
    """
    if kind.code != "D02":
        return True, None
    have = {kind.part}
    for d in documents:
        if d.todo_id == todo.id and d.recognition_status == "recognized":
            other = parse_kind(d.document_kind)
            if other and other.code == "D02":
                have.add(other.part)
    if "boarding_proof" in have or {"ticket", "boarding_pass"} <= have:
        return True, None
    missing = "登機證" if "ticket" in have else "機票"
    return False, f"已收到，還缺{missing}（或改傳一份搭機證明）"

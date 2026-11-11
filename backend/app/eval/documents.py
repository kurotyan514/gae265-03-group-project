"""文件辨識驗收（#68）：用 repo 外的資料集量 6 號的準確率。不在執行路徑上，只由 `make eval-documents` 執行。

資料集放在 `DOCUMENT_EVAL_DIR`（repo 外），裡面有原檔與 `answers.json`：

    [
      {"file": "flight_delay_01.jpg", "code": "D01", "expect": "recognized",
       "personal": ["王小明", "A123456789"]},
      ...
    ]

- `code`：通過時應辨識出的文件代碼；`expect`：狀態或允許的狀態清單（含 incomplete）。
- `personal`：文件上的個資，用來檢查 reason 與文件種類有沒有洩漏。
- `todo_complete`、`matched_todo_id`：預期待辦完成狀態與對應 id；明寫 null 表示不可對應。
- `fixture`：相對於資料集的事件檔（ctx、user）；`group`：supported／unsupported／format／storage。
- `profile`：authorized_storage_success／no_google_access／storage_failure，全部使用假 Drive。
- `score=false` 搭配 `review_note`：待確認案例不執行，另外列出，不進入準確率分母。
  舊格式仍可用，但未提供 todo_complete 時，報告會標示未驗證完成預期。

agent 和正式環境一樣由 `create_document_agent` 建立（照片走設定裡的 Azure Document Intelligence，`--model read|layout` 可切換）；只有 Drive 與 Google 授權用假的，不會存到任何人的雲端。
報告寫回資料集資料夾（不進 repo）。錯勾待辦、個資外洩、未存成功卻回通過，三項必須是 0。
"""

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator

from app.agents.document import DocumentAgent, create_document_agent
from app.agents.document.codes import SPECS, matching_todos, parse_kind
from app.agents.document.rules import RULES_FILE
from app.agents.document.storage import StorageFailed
from app.contracts import (
    IncidentContext,
    PolicySummary,
    Recognition,
    TodoView,
    UploadedFile,
    UserContext,
)
from app.core.config import settings
from app.seed import INCIDENT_CATALOG_PATH

logger = logging.getLogger(__name__)

# 辨識結果的狀態以契約為準：契約加了新狀態，這裡會跟著認得
STATUSES = frozenset(get_args(Recognition.model_fields["status"].annotation))

Group = Literal["supported", "unsupported", "format", "storage"]
GROUPS: tuple[str, ...] = get_args(Group)


class _Drive:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved: set[str] = set()

    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        return f"folder-{name}"

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        if self.fail:
            raise StorageFailed("評估用的假儲存失敗")
        file_id = f"eval-{uuid.uuid4().hex[:8]}"
        self.saved.add(file_id)
        return file_id

    async def rename(self, token: str, file_id: str, name: str) -> None:
        return None

    async def download(self, token: str, file_id: str) -> bytes:
        return b""

    async def delete(self, token: str, file_id: str) -> None:
        return None


class _Google:
    def __init__(self, *, authorized: bool = True) -> None:
        self.authorized = authorized

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return "eval-token" if self.authorized else None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None  # 沒有平台的資料夾：6 號自己找或建（展示用的假雲端）


class EvalCase(BaseModel):
    """評估器專用答案，絕不放進 IncidentContext 或 UploadedFile。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    case_id: str | None = None
    file: str
    code: str | None
    expect: str | list[str]
    personal: list[str] = []
    todo_complete: StrictBool | None = None
    matched_todo_id: uuid.UUID | None = None
    fixture: str | None = None
    group: Group = "supported"
    profile: Literal[
        "authorized_storage_success", "no_google_access", "storage_failure"
    ] = "authorized_storage_success"
    score: StrictBool = True
    review_note: str | None = None

    @field_validator("code")
    @classmethod
    def _known_code(cls, value: str | None) -> str | None:
        # 文件代碼以 6 號的註冊表（codes.SPECS）為準，新增代碼不用回來改這裡
        if value is not None and value not in SPECS:
            raise ValueError(f"未知的文件代碼；目前有：{'、'.join(sorted(SPECS))}")
        return value

    @field_validator("expect")
    @classmethod
    def _known_status(cls, value: str | list[str]) -> str | list[str]:
        unknown = {value} if isinstance(value, str) else set(value)
        if unknown - STATUSES:
            raise ValueError(f"未知的辨識狀態；目前有：{'、'.join(sorted(STATUSES))}")
        return value

    @property
    def statuses(self) -> list[str]:
        return [self.expect] if isinstance(self.expect, str) else self.expect


class EvalFixture(BaseModel):
    ctx: IncidentContext
    user: UserContext


@dataclass
class Report:
    total: int = 0
    correct: int = 0
    wrong_todo: list[str] = field(default_factory=list)
    personal_leak: list[str] = field(default_factory=list)
    recognized_without_storage: list[str] = field(default_factory=list)
    unexpected_recognized: list[str] = field(default_factory=list)
    storage_violation: list[str] = field(default_factory=list)
    skipped: list[dict[str, object]] = field(default_factory=list)
    rows: list[dict[str, object]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.total, 3) if self.total else 0.0

    @property
    def zero_tolerance_ok(self) -> bool:
        return not (
            self.wrong_todo
            or self.personal_leak
            or self.recognized_without_storage
            or self.unexpected_recognized
            or self.storage_violation
        )

    @property
    def groups(self) -> dict[str, dict[str, int | float | None]]:
        """每一組都列出，沒有案例的組別分母是 0、分數是 None，看得出「這次沒測」。"""
        groups: dict[str, dict[str, int | float | None]] = {}
        for name in GROUPS:
            rows = [row for row in self.rows if row["group"] == name]
            correct = sum(bool(row["ok"]) for row in rows)
            groups[name] = {
                "total": len(rows),
                "correct": correct,
                "accuracy": round(correct / len(rows), 3) if rows else None,
            }
        return groups


def _phases() -> dict[str, str]:
    """理賠文件規則（incident_catalog.json）裡每個文件代碼的階段。"""
    catalog = json.loads(INCIDENT_CATALOG_PATH.read_text(encoding="utf-8"))
    return {d["code"]: d["phase"] for d in catalog["documents"]}


def _context() -> tuple[IncidentContext, dict[uuid.UUID, str]]:
    """沒給 fixture 時的預設事件：6 號認得的每種文件各一項待辦（用 document_code 對應，不靠標題）。"""
    phases = _phases()
    todos = [
        TodoView.model_validate(
            {
                "id": uuid.uuid4(),
                "phase": phases[code],
                "title": spec.name,
                "document_code": code,
            }
        )
        for code, spec in SPECS.items()
    ]
    ctx = IncidentContext(
        incident_id=uuid.uuid4(),
        title="驗收",
        description="",
        status="open",
        policy=PolicySummary(
            plan_id="eval",
            plan_name="驗收",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            insurance_codes=[],
            coverages=[],
        ),
        todos=todos,
    )
    return ctx, {t.id: code for t, code in zip(todos, SPECS, strict=True)}


def _content_type(path: Path) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(path.suffix.lower(), "application/octet-stream")


async def evaluate(dataset: Path, agent: DocumentAgent) -> Report:
    raw = json.loads((dataset / "answers.json").read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "答案須為非空案例清單；原始 ground_truth 須先轉換，不可直接評分"
        )
    cases = [EvalCase.model_validate(answer) for answer in raw]
    prepared: list[tuple[EvalCase, IncidentContext, UserContext]] = []
    # 全部先驗證，避免跑到一半才發現後面的 fixture 或檔案壞了。
    for case in cases:
        if not case.statuses:
            raise ValueError("預期狀態清單不可為空")
        if not case.score:
            if not case.review_note:
                raise ValueError("待確認案例必須說明不計分原因")
            continue
        if case.fixture:
            fixture = EvalFixture.model_validate_json(
                (dataset / case.fixture).read_text(encoding="utf-8")
            )
            ctx, user = fixture.ctx, fixture.user
        else:
            ctx, _ = _context()
            user = UserContext(user_id=uuid.uuid4(), email="eval@example.com")
        if case.matched_todo_id is not None and case.matched_todo_id not in {
            t.id for t in ctx.todos if t.status != "not_applicable"
        }:
            raise ValueError("預期對應的待辦不存在或不適用，請確認 fixture")
        if not (dataset / case.file).is_file():
            raise ValueError("評估文件不存在，尚未執行辨識")
        prepared.append((case, ctx, user))
    report = Report()
    report.skipped = [
        {
            "case_id": c.case_id,
            "file": c.file,
            "group": c.group,
            "reason": c.review_note,
        }
        for c in cases
        if not c.score
    ]
    for case, ctx, user in prepared:
        path = dataset / case.file
        drive = _Drive(fail=case.profile == "storage_failure")
        # 複製傳進來的 agent，其他設定（含之後新增的參數）原樣帶過來，只改下面兩項：
        case_agent = copy.copy(agent)
        case_agent.drive = drive  # 每個案例換新的假 Drive，才驗得到這次有沒有真的存
        case_agent.dev_token = None  # 刻意清掉：不能用開發用 token 跳過「未授權」情境
        result = await case_agent.recognize(
            ctx,
            UploadedFile(
                file_name=path.name,
                content_type=_content_type(path),
                content=path.read_bytes(),
            ),
            user,
            _Google(authorized=case.profile != "no_google_access"),
        )
        kind = parse_kind(result.document_kind)
        got_code = kind.code if kind else None
        name = case.file
        active_ids = {t.id for t in ctx.todos if t.status != "not_applicable"}
        bad_match = (
            result.matched_todo_id is not None
            and result.matched_todo_id not in active_ids
        )
        if "matched_todo_id" in case.model_fields_set:
            bad_match |= result.matched_todo_id != case.matched_todo_id
        elif result.matched_todo_id is not None:
            allowed = (
                {t.id for t in matching_todos(case.code, ctx.todos)}
                if case.code
                else set()
            )
            bad_match |= result.matched_todo_id not in allowed
        bad_completion = (
            case.todo_complete is not None
            and result.todo_complete != case.todo_complete
        )
        wrong_todo = bad_match or (
            result.todo_complete
            and (
                case.todo_complete is False
                or result.matched_todo_id is None
                or result.status != "recognized"
                or "recognized" not in case.statuses
            )
        )
        unexpected = result.status == "recognized" and (
            "recognized" not in case.statuses or case.group in {"unsupported", "format"}
        )
        unwritten = (
            result.status == "recognized" and result.storage_path not in drive.saved
        )
        storage_violation = (
            bool(result.storage_path) and result.storage_path not in drive.saved
        ) or (
            (
                result.status in {"failed", "incomplete"}
                or case.profile in {"no_google_access", "storage_failure"}
            )
            and bool(result.storage_path or drive.saved)
        )
        exposed = f"{result.reason or ''} {result.document_kind or ''}"
        leaked = any(p and p in exposed for p in case.personal)
        if wrong_todo:
            report.wrong_todo.append(name)
        if unexpected:
            report.unexpected_recognized.append(name)
        if leaked:
            report.personal_leak.append(name)
        if unwritten:
            report.recognized_without_storage.append(name)
        if storage_violation:
            report.storage_violation.append(name)
        ok = (
            result.status in case.statuses
            and (result.status != "recognized" or got_code == case.code)
            and not (
                bad_completion
                or bad_match
                or wrong_todo
                or unexpected
                or unwritten
                or storage_violation
                or leaked
            )
        )
        report.total += 1
        report.correct += int(ok)
        report.rows.append(
            {
                "case_id": case.case_id,
                "file": name,
                "group": case.group,
                "profile": case.profile,
                "expect": case.expect,
                "code": case.code,
                "status": result.status,
                "got_code": got_code,
                "expected_todo_complete": case.todo_complete,
                "todo_complete": result.todo_complete,
                "completion_checked": case.todo_complete is not None,
                "matched_todo_id": str(result.matched_todo_id)
                if result.matched_todo_id
                else None,
                "storage_present": bool(result.storage_path),
                "storage_verified": result.storage_path in drive.saved,
                "ok": ok,
                "confidence": result.confidence,
                "reason": "偵測到個資，原始回覆不寫入報告" if leaked else result.reason,
            }
        )
    return report


def _agent(model: Literal["read", "layout"] | None) -> DocumentAgent:
    """和正式環境用同一個建立函式（OCR、規則、門檻都一樣），只把 Drive 換成假的。"""
    return create_document_agent(drive=_Drive(), ocr_model=model)


def main() -> None:
    parser = argparse.ArgumentParser(description="文件辨識驗收")
    parser.add_argument("--dataset", type=Path, default=settings.DOCUMENT_EVAL_DIR)
    parser.add_argument("--model", choices=["read", "layout"], default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.dataset is None:
        raise SystemExit(
            "請在 .env 設定 DOCUMENT_EVAL_DIR，或用 --dataset 指定資料集資料夾"
        )
    runner = _agent(args.model)
    report = asyncio.run(evaluate(args.dataset, runner))
    model = args.model or settings.AZURE_DOCUMENT_INTELLIGENCE_MODEL
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    out = args.dataset / f"report-{model}-{stamp}.json"
    with out.open("x", encoding="utf-8") as handle:
        json.dump(
            {
                "model": model,
                "ocr_configured": runner.ocr is not None,
                "storage": "fake_drive",
                "metric_note": "accuracy 為計分案例符合率；混合支援類型、防誤勾與格式測試，應看 groups 解讀，不代表純文件分類準確率",
                "created_at_utc": stamp,
                "answers_sha256": hashlib.sha256(
                    (args.dataset / "answers.json").read_bytes()
                ).hexdigest(),
                "code_sha256": {
                    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in [
                        Path(__file__),
                        *sorted(
                            Path(__file__)
                            .parents[1]
                            .joinpath("agents/document")
                            .glob("*.py")
                        ),
                        RULES_FILE,
                    ]
                },
                "accuracy": report.accuracy,
                "total": report.total,
                "correct": report.correct,
                "groups": report.groups,
                "skipped": report.skipped,
                "wrong_todo": report.wrong_todo,
                "personal_leak": report.personal_leak,
                "recognized_without_storage": report.recognized_without_storage,
                "unexpected_recognized": report.unexpected_recognized,
                "storage_violation": report.storage_violation,
                "zero_tolerance_ok": report.zero_tolerance_ok,
                "rows": report.rows,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    logger.info(
        "全部計分案例符合率 %s/%s（%.1f%%，含防誤勾，非純分類準確率），模型 %s",
        report.correct,
        report.total,
        report.accuracy * 100,
        model,
    )
    logger.info(
        "錯勾待辦 %s、個資外洩 %s、未存成功卻通過 %s",
        len(report.wrong_todo),
        len(report.personal_leak),
        len(report.recognized_without_storage),
    )
    logger.info("報告：%s", out)
    logger.info("分組成績：%s；待確認未執行 %s 案", report.groups, len(report.skipped))
    if not report.zero_tolerance_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

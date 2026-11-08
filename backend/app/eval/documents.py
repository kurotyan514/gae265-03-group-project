"""文件辨識驗收（#68）：用 repo 外的資料集量 6 號的準確率。不在執行路徑上，只由 `make eval-documents` 執行。

資料集放在 `DOCUMENT_EVAL_DIR`（repo 外），裡面有原檔與 `answers.json`：

    [
      {"file": "flight_delay_01.jpg", "code": "D01", "expect": "recognized",
       "personal": ["王小明", "A123456789"]},
      ...
    ]

- `code`：正確的文件代碼；`expect`：正確的辨識結果（recognized／needs_review／failed）。
- `personal`：文件上的個資，用來檢查 reason 與文件種類有沒有洩漏。

照片走設定裡的 Azure Document Intelligence（`--model read|layout` 可切換）；Drive 與 Google 授權用假的，不會存到任何人的雲端。
報告寫回資料集資料夾（不進 repo）。錯勾待辦、個資外洩、未存成功卻回通過，三項必須是 0。
"""

import argparse
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.agents.document import DocumentAgent
from app.agents.document.codes import parse_kind
from app.agents.document.reader import AzureDocumentIntelligence
from app.agents.document.rules import load_rules
from app.contracts import (
    IncidentContext,
    PolicySummary,
    TodoView,
    UploadedFile,
    UserContext,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

TODOS = {
    "D01": "請航空公司開立班機延誤／取消證明",
    "D02": "保留原定機票與登機證",
    "D10": "填寫理賠申請書",
}


class _Drive:
    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        return f"folder-{name}"

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        return f"eval-{uuid.uuid4().hex[:8]}"

    async def rename(self, token: str, file_id: str, name: str) -> None:
        return None


class _Google:
    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return "eval-token"

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None  # 沒有平台的資料夾：6 號自己找或建（展示用的假雲端）


@dataclass
class Report:
    total: int = 0
    correct: int = 0
    wrong_todo: list[str] = field(default_factory=list)
    personal_leak: list[str] = field(default_factory=list)
    recognized_without_storage: list[str] = field(default_factory=list)
    rows: list[dict[str, object]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.total, 3) if self.total else 0.0

    @property
    def zero_tolerance_ok(self) -> bool:
        return not (
            self.wrong_todo or self.personal_leak or self.recognized_without_storage
        )


def _context() -> tuple[IncidentContext, dict[uuid.UUID, str]]:
    todos = [
        TodoView(
            id=uuid.uuid4(),
            phase="after_return" if code == "D10" else "on_site",
            title=title,
        )
        for code, title in TODOS.items()
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
    return ctx, {t.id: code for t, code in zip(todos, TODOS, strict=True)}


def _content_type(path: Path) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(path.suffix.lower(), "application/octet-stream")


async def evaluate(dataset: Path, agent: DocumentAgent) -> Report:
    answers = json.loads((dataset / "answers.json").read_text(encoding="utf-8"))
    user = UserContext(user_id=uuid.uuid4(), email="eval@example.com")
    report = Report()
    for answer in answers:
        path = dataset / answer["file"]
        ctx, todo_codes = _context()
        result = await agent.recognize(
            ctx,
            UploadedFile(
                file_name=path.name,
                content_type=_content_type(path),
                content=path.read_bytes(),
            ),
            user,
            _Google(),
        )
        kind = parse_kind(result.document_kind)
        got_code = kind.code if kind else None
        ok = result.status == answer["expect"] and (
            result.status != "recognized" or got_code == answer["code"]
        )
        report.total += 1
        report.correct += ok
        name = answer["file"]
        if result.todo_complete and (
            result.matched_todo_id is None
            or todo_codes.get(result.matched_todo_id) != answer["code"]
        ):
            report.wrong_todo.append(name)
        exposed = f"{result.reason or ''} {result.document_kind or ''}"
        if any(p and p in exposed for p in answer.get("personal", [])):
            report.personal_leak.append(name)
        if result.status == "recognized" and not result.storage_path:
            report.recognized_without_storage.append(name)
        report.rows.append(
            {
                "file": name,
                "expect": answer["expect"],
                "code": answer["code"],
                "status": result.status,
                "got_code": got_code,
                "ok": ok,
                "confidence": result.confidence,
                "reason": result.reason,
            }
        )
    return report


def _agent(model: str | None) -> DocumentAgent:
    ocr = None
    if (
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        and settings.AZURE_DOCUMENT_INTELLIGENCE_API_KEY
    ):
        ocr = AzureDocumentIntelligence(
            settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
            settings.AZURE_DOCUMENT_INTELLIGENCE_API_KEY.get_secret_value(),
            model=model or settings.AZURE_DOCUMENT_INTELLIGENCE_MODEL,  # pyright: ignore[reportArgumentType]
            api_version=settings.AZURE_DOCUMENT_INTELLIGENCE_API_VERSION,
        )
    return DocumentAgent(
        ocr=ocr,
        drive=_Drive(),
        rules=load_rules(),
        threshold=settings.DOCUMENT_FIELD_CONFIDENCE,
    )


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
    report = asyncio.run(evaluate(args.dataset, _agent(args.model)))
    model = args.model or settings.AZURE_DOCUMENT_INTELLIGENCE_MODEL
    out = args.dataset / f"report-{model}.json"
    out.write_text(
        json.dumps(
            {
                "model": model,
                "accuracy": report.accuracy,
                "total": report.total,
                "wrong_todo": report.wrong_todo,
                "personal_leak": report.personal_leak,
                "recognized_without_storage": report.recognized_without_storage,
                "rows": report.rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info(
        "準確率 %s/%s（%.1f%%），模型 %s",
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
    if not report.zero_tolerance_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

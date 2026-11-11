"""文件辨識驗收程式：用暫存資料夾當資料集，Azure 沒設定時只跑電子 PDF。"""

import json
import sys
import uuid
from pathlib import Path

import pytest
from app.agents.document.recognizer import DocumentAgent
from app.contracts import FactView, Recognition
from app.eval import documents
from app.eval.documents import _agent, evaluate

from tests.agents.document_helpers import DELAY_TEXT, USER, agent, context, pdf


async def test_evaluate_reports_accuracy_and_zero_tolerance(tmp_path: Path) -> None:
    (tmp_path / "delay.pdf").write_bytes(pdf(DELAY_TEXT + "\n被保險人：王小明"))
    (tmp_path / "pass.pdf").write_bytes(pdf("BOARDING PASS\nBR198"))
    (tmp_path / "answers.json").write_text(
        json.dumps(
            [
                {
                    "file": "delay.pdf",
                    "code": "D01",
                    "expect": "recognized",
                    "personal": ["王小明"],
                },
                {"file": "pass.pdf", "code": "D02", "expect": "recognized"},
            ]
        ),
        encoding="utf-8",
    )
    report = await evaluate(tmp_path, _agent(None))
    assert report.total == 2 and report.accuracy == 1.0
    assert report.zero_tolerance_ok


def dataset(tmp_path: Path, answers: list[dict], text: str = DELAY_TEXT) -> Path:
    (tmp_path / "document.pdf").write_bytes(pdf(text))
    (tmp_path / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    return tmp_path


async def test_single_boarding_pass_is_not_a_completed_todo(tmp_path: Path) -> None:
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D02",
                    "expect": "recognized",
                    "todo_complete": False,
                }
            ],
            "BOARDING PASS",
        ),
        agent(),
    )
    assert report.correct == 1
    assert report.rows[0]["todo_complete"] is False
    assert report.rows[0]["completion_checked"] is True


async def test_wrong_completion_is_a_zero_tolerance_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(self, ctx, file, user, google):  # noqa: ARG001
        return Recognition(
            status="recognized",
            document_kind="D02 登機證",
            matched_todo_id=ctx.todos[1].id,
            todo_complete=True,
            storage_path="invented",
        )

    monkeypatch.setattr(DocumentAgent, "recognize", bad)
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D02",
                    "expect": "recognized",
                    "todo_complete": False,
                }
            ],
        ),
        agent(),
    )
    assert report.correct == 0
    assert report.wrong_todo == ["document.pdf"]
    assert not report.zero_tolerance_ok


async def test_unexpected_recognition_is_caught_even_without_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(self, ctx, file, user, google):  # noqa: ARG001
        return Recognition(status="recognized", storage_path="invented")

    monkeypatch.setattr(DocumentAgent, "recognize", bad)
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": None,
                    "expect": ["needs_review", "failed"],
                    "todo_complete": False,
                    "matched_todo_id": None,
                    "group": "unsupported",
                }
            ],
        ),
        agent(),
    )
    assert report.unexpected_recognized == ["document.pdf"]
    assert not report.zero_tolerance_ok


async def test_nonempty_but_unwritten_storage_id_is_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(self, ctx, file, user, google):  # noqa: ARG001
        return Recognition(
            status="recognized",
            document_kind="D01 延誤／取消證明",
            storage_path="invented",
        )

    monkeypatch.setattr(DocumentAgent, "recognize", bad)
    report = await evaluate(
        dataset(
            tmp_path, [{"file": "document.pdf", "code": "D01", "expect": "recognized"}]
        ),
        agent(),
    )
    assert report.recognized_without_storage == ["document.pdf"]
    assert report.correct == 0


async def test_fixture_preserves_event_facts_user_and_todo_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context()
    ctx = ctx.model_copy(
        update={
            "todos": [ctx.todos[0].model_copy(update={"document_code": "D01"})],
            "facts": [FactView(fact_key="flight_number", label="航班", value="SMP731")],
        }
    )
    recognize = DocumentAgent.recognize
    seen = []

    async def capture(self, ctx, file, user, google):
        assert ctx.facts[0].value == "SMP731"
        assert user == USER
        assert ctx.policy.plan_id == "fubon_advanced"
        seen.append(ctx.incident_id)
        return await recognize(self, ctx, file, user, google)

    monkeypatch.setattr(DocumentAgent, "recognize", capture)
    (tmp_path / "fixture.json").write_text(
        json.dumps(
            {"ctx": ctx.model_dump(mode="json"), "user": USER.model_dump(mode="json")}
        ),
        encoding="utf-8",
    )
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D01",
                    "expect": "recognized",
                    "fixture": "fixture.json",
                    "todo_complete": True,
                    "matched_todo_id": str(ctx.todos[0].id),
                }
            ],
        ),
        agent(),
    )
    assert report.correct == 1
    assert report.rows[0]["matched_todo_id"] == str(ctx.todos[0].id)
    assert seen == [ctx.incident_id]


async def test_matching_a_wrong_todo_is_caught_without_ticking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(self, ctx, file, user, google):  # noqa: ARG001
        return Recognition(status="needs_review", matched_todo_id=ctx.todos[0].id)

    monkeypatch.setattr(DocumentAgent, "recognize", bad)
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": None,
                    "expect": "needs_review",
                    "todo_complete": False,
                    "matched_todo_id": None,
                }
            ],
        ),
        agent(),
    )
    assert report.correct == 0
    assert report.wrong_todo == ["document.pdf"]


async def test_group_scores_and_unscored_cases_have_separate_denominators(
    tmp_path: Path,
) -> None:
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D01",
                    "expect": "recognized",
                    "group": "supported",
                },
                {
                    "file": "document.pdf",
                    "code": None,
                    "expect": ["needs_review", "failed"],
                    "group": "unsupported",
                },
                {
                    "file": "missing.jpg",
                    "code": "D01",
                    "expect": "needs_review",
                    "score": False,
                    "review_note": "日期相符性尚未納入本次評估",
                },
            ],
        ),
        agent(),
    )
    assert report.total == 2 and report.correct == 1
    assert report.groups["supported"]["total"] == 1
    assert report.groups["unsupported"]["correct"] == 0
    assert len(report.skipped) == 1


@pytest.mark.parametrize("profile", ["no_google_access", "storage_failure"])
async def test_auth_and_storage_profiles_do_not_claim_success(
    tmp_path: Path, profile: str
) -> None:
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D01",
                    "expect": "needs_review",
                    "todo_complete": False,
                    "matched_todo_id": None,
                    "profile": profile,
                }
            ],
        ),
        agent(),
    )
    assert report.correct == 1
    assert report.rows[0]["storage_present"] is False
    assert report.rows[0]["todo_complete"] is False


async def test_incomplete_file_is_reported_without_storage(tmp_path: Path) -> None:
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D01",
                    "expect": "incomplete",
                    "todo_complete": False,
                    "matched_todo_id": None,
                }
            ],
            "班機延誤證明",
        ),
        agent(),
    )
    assert report.correct == 1
    assert report.rows[0]["storage_present"] is False


async def test_storage_failure_cannot_claim_a_pending_file_was_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(self, ctx, file, user, google):  # noqa: ARG001
        return Recognition(status="needs_review", storage_path="invented")

    monkeypatch.setattr(DocumentAgent, "recognize", bad)
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D01",
                    "expect": "needs_review",
                    "profile": "storage_failure",
                }
            ],
        ),
        agent(),
    )
    assert report.storage_violation == ["document.pdf"]
    assert report.correct == 0


async def test_no_google_profile_does_not_use_a_development_token(
    tmp_path: Path,
) -> None:
    base = agent()
    base.dev_token = "development-token"
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": "D01",
                    "expect": "needs_review",
                    "profile": "no_google_access",
                    "todo_complete": False,
                    "matched_todo_id": None,
                }
            ],
        ),
        base,
    )
    assert report.correct == 1
    assert report.rows[0]["storage_present"] is False


async def test_fixture_expected_todo_must_exist_before_evaluation(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="待辦"):
        await evaluate(
            dataset(
                tmp_path,
                [
                    {
                        "file": "document.pdf",
                        "code": "D01",
                        "expect": "recognized",
                        "matched_todo_id": str(uuid.uuid4()),
                    }
                ],
            ),
            agent(),
        )


async def test_personal_leak_is_not_repeated_in_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def bad(self, ctx, file, user, google):  # noqa: ARG001
        return Recognition(status="needs_review", reason="秘密測試姓名")

    monkeypatch.setattr(DocumentAgent, "recognize", bad)
    report = await evaluate(
        dataset(
            tmp_path,
            [
                {
                    "file": "document.pdf",
                    "code": None,
                    "expect": "needs_review",
                    "personal": ["秘密測試姓名"],
                }
            ],
        ),
        agent(),
    )
    assert report.personal_leak == ["document.pdf"]
    assert "秘密測試姓名" not in json.dumps(report.rows, ensure_ascii=False)
    assert report.correct == 0


def test_cli_reports_are_separate_and_include_group_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset(
        tmp_path,
        [
            {
                "file": "document.pdf",
                "code": "D01",
                "expect": "recognized",
                "todo_complete": True,
            }
        ],
    )
    monkeypatch.setattr(
        sys, "argv", ["documents", "--dataset", str(tmp_path), "--model", "read"]
    )
    monkeypatch.setattr(documents, "_agent", lambda model: agent())
    documents.main()
    documents.main()
    reports = list(tmp_path.glob("report-read-*.json"))
    assert len(reports) == 2
    for path in reports:
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["groups"]["supported"]["correct"] == 1
        assert body["answers_sha256"]
        assert body["code_sha256"]["documents.py"]
        assert body["storage"] == "fake_drive"


async def test_invalid_later_fixture_is_rejected_before_any_document_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    async def spy(self, ctx, file, user, google):  # noqa: ARG001
        seen.append(True)
        return Recognition(status="needs_review")

    monkeypatch.setattr(DocumentAgent, "recognize", spy)
    with pytest.raises(ValueError, match="待辦"):
        await evaluate(
            dataset(
                tmp_path,
                [
                    {"file": "document.pdf", "code": "D01", "expect": "recognized"},
                    {
                        "file": "document.pdf",
                        "code": "D01",
                        "expect": "recognized",
                        "matched_todo_id": str(uuid.uuid4()),
                    },
                ],
            ),
            agent(),
        )
    assert not seen


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("code", "D99", "未知的文件代碼"), ("expect", "approved", "未知的辨識狀態")],
)
async def test_unknown_code_or_status_is_rejected_with_the_known_values(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    case = {"file": "document.pdf", "code": "D01", "expect": "recognized"}
    case[field] = value
    with pytest.raises(ValueError, match=message):
        await evaluate(dataset(tmp_path, [case]), agent())


def test_known_codes_and_statuses_come_from_the_registry_and_contract() -> None:
    from app.agents.document.codes import SPECS

    assert documents.STATUSES == {"recognized", "needs_review", "incomplete", "failed"}
    ctx, codes = documents._context()
    assert sorted(codes.values()) == sorted(SPECS)
    phases = {codes[t.id]: t.phase for t in ctx.todos}
    assert phases == {"D01": "on_site", "D02": "on_site", "D10": "after_return"}


async def test_groups_without_cases_are_listed_with_zero_total(tmp_path: Path) -> None:
    report = await evaluate(
        dataset(
            tmp_path,
            [{"file": "document.pdf", "code": "D01", "expect": "recognized"}],
        ),
        agent(),
    )
    assert report.groups["supported"] == {"total": 1, "correct": 1, "accuracy": 1.0}
    assert report.groups["storage"] == {"total": 0, "correct": 0, "accuracy": None}


async def test_each_case_keeps_the_agent_settings_but_drops_the_dev_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[DocumentAgent] = []

    async def spy(self, ctx, file, user, google):  # noqa: ARG001
        seen.append(self)
        return Recognition(status="needs_review")

    runner = agent()
    runner.dev_token = "dev-fake-token"
    runner.threshold = 0.42
    monkeypatch.setattr(DocumentAgent, "recognize", spy)
    await evaluate(
        dataset(
            tmp_path,
            [{"file": "document.pdf", "code": "D01", "expect": "needs_review"}],
        ),
        runner,
    )
    (case_agent,) = seen
    assert case_agent is not runner and runner.dev_token == "dev-fake-token"
    assert case_agent.dev_token is None
    assert case_agent.threshold == 0.42 and case_agent.rules is runner.rules
    assert case_agent.drive is not runner.drive


def test_cli_agent_is_built_like_production_with_a_fake_drive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.document.reader import AzureDocumentIntelligence
    from app.core.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "DOCUMENT_DEV_FAKE_STORAGE", True)
    monkeypatch.setattr(settings, "DOCUMENT_FIELD_CONFIDENCE", 0.7)
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "https://x")
    monkeypatch.setattr(settings, "AZURE_DOCUMENT_INTELLIGENCE_API_KEY", SecretStr("k"))
    runner = _agent("layout")
    assert isinstance(runner.drive, documents._Drive)
    assert runner.dev_token is None and runner.threshold == 0.7
    assert isinstance(runner.ocr, AzureDocumentIntelligence)
    assert runner.ocr.model == "layout"

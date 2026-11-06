"""文件辨識驗收程式：用暫存資料夾當資料集，Azure 沒設定時只跑電子 PDF。"""

import json
from pathlib import Path

from app.eval.documents import _agent, evaluate

from tests.agents.document_helpers import DELAY_TEXT, pdf


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

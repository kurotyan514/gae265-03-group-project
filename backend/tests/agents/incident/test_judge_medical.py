"""就醫的判斷（安達海外突發疾病健康保險（乙型）CHUBB04，第四、五、六、八條）：一列一個案例。"""

from datetime import date

import pytest
from app.agents.incident.judge import judge_medical

START, END = date(2027, 9, 6), date(2027, 9, 11)
REMINDER = "出發前九十日內曾就同一疾病就診、或以出國就醫為目的者，依條款不賠"
BASE = {"date": "2027/09/07"}


@pytest.mark.parametrize(
    ("known", "conclusion", "reason"),
    [
        (
            {**BASE, "date": "2027/09/20", "kind": "生病", "hosp": "否"},
            "excluded",
            "事故不在保險期間內，依條款不在保障範圍",
        ),
        (
            {**BASE, "kind": "受傷", "hosp": "否"},
            "insufficient",
            "受傷屬於傷害醫療，這部分的條款尚未核對，請向保險公司確認",
        ),
        ({**BASE}, "insufficient", "需確認是生病還是受傷"),
        ({**BASE, "kind": "不知道"}, "insufficient", "需確認是生病還是受傷"),
        (
            {**BASE, "kind": "生病", "hosp": "否"},
            "applicable",
            "海外突發疾病門診可申請醫療保險金，依收據在保單額度內理賠",
        ),
        (
            {**BASE, "kind": "生病", "hosp": "是"},
            "applicable",
            "海外突發疾病住院可申請醫療保險金，依收據在保單額度內理賠",
        ),
        (
            {**BASE, "kind": "生病", "hosp": "不知道"},
            "applicable",
            "海外突發疾病就醫可申請醫療保險金，依收據在保單額度內理賠",
        ),
        (
            {**BASE, "kind": "生病"},
            "applicable",
            "海外突發疾病就醫可申請醫療保險金，依收據在保單額度內理賠",
        ),
    ],
    ids=[
        "事故日不在保險期間",
        "受傷",
        "沒有回答生病或受傷",
        "生病或受傷答不知道",
        "生病門診",
        "生病住院",
        "生病不知道有沒有住院",
        "生病還沒問住院",
    ],
)
def test_就醫的判斷(known: dict[str, str], conclusion: str, reason: str) -> None:
    judged = judge_medical(known, START, END)

    assert judged.conclusion == conclusion
    if conclusion == "applicable":
        assert judged.reason == f"{reason}；{REMINDER}"
    else:
        assert judged.reason == reason


def test_沒有保險期間時_不判斷事故日期() -> None:
    assert (
        judge_medical({**BASE, "kind": "生病", "hosp": "否"}).conclusion == "applicable"
    )


def test_理由不寫金額或百分比() -> None:
    judged = judge_medical({**BASE, "kind": "生病", "hosp": "是"}, START, END)

    assert not any(ch.isdigit() for ch in judged.reason.replace("九十", ""))
    assert "%" not in judged.reason and "％" not in judged.reason

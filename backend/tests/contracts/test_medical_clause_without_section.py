"""就醫的結論用「整份險種」回報（沒有章名），平台要接受、建待辦、理賠頁看得到。

背景：安達基礎型的四個險種（CHUBB01～04）在條款庫裡沒有章名，平台依章名比對事故類型的保障，
就醫事件的 `event.coverages` 是空的（#233 第 1 項）。5 號改成從保單的保障挑出已核對的險種回報，
所以要先確認：5 號回報一個平台沒有列在事故類型保障裡的險種結論時，平台後面三步都照常運作。

用回傳指定結果的 5 號走平台的 API；不經過真實的 5 號。
"""

from datetime import date

import pytest
from app.contracts import AgentServices, IncidentContext, IncidentReply
from app.contracts.incident_agent import ClauseUpdate, FactUpdate
from app.models import Policy, User
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")

REASON = "海外突發疾病就醫可申請醫療保險金"
MEDICAL_FACTS = {
    "event_type": ("事故類型", "medical"),
    "date": ("發生日期", "2026/11/10"),
    "kind": ("生病或受傷", "生病"),
    "hosp": ("是否住院", "否"),
    "paid": ("是否已支付醫療費", "是"),
}


class MedicalAgent:
    """第一句追問；使用者回答後，用整份險種（沒有章名）回報就醫的結論。"""

    async def start(
        self, ctx: IncidentContext, services: AgentServices
    ) -> IncidentReply:
        return IncidentReply(message="是生病，還是受傷？")

    async def reply(
        self,
        ctx: IncidentContext,
        user_message: str,
        input_mode: str,
        services: AgentServices,
    ) -> IncidentReply:
        return IncidentReply(
            message="整理好了。",
            incident_type_code="medical",
            facts=[
                FactUpdate(fact_key=k, label=label, value=value, sort_order=i)
                for i, (k, (label, value)) in enumerate(MEDICAL_FACTS.items())
            ],
            clauses=[
                ClauseUpdate(
                    insurance_code="CHUBB04", conclusion="applicable", reason=REASON
                ),
                *(
                    ClauseUpdate(
                        insurance_code=code,
                        conclusion="insufficient",
                        reason="需由保險公司確認",
                    )
                    for code in ("CHUBB01", "CHUBB02", "CHUBB03")
                ),
            ],
            finished=True,
        )


@pytest.fixture
async def chubb_policy(
    session: AsyncSession, user: User, catalog_loaded: None
) -> Policy:
    assert catalog_loaded is None
    p = Policy(
        user_id=user.id,
        display_name="安達基礎型",
        plan_id="chubb_basic",
        sum_insured=3_000_000,
        start_date=date(2026, 11, 10),
        end_date=date(2026, 11, 11),
    )
    session.add(p)
    await session.commit()
    return p


class StrangerInsuranceAgent(MedicalAgent):
    """對照：回報這張保單沒有的險種。"""

    async def reply(self, ctx, user_message, input_mode, services):  # type: ignore[override]
        reply = await super().reply(ctx, user_message, input_mode, services)
        return reply.model_copy(
            update={
                "clauses": [
                    ClauseUpdate(insurance_code="FUBON03", conclusion="applicable")
                ]
            }
        )


async def run(
    client: AsyncClient,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
    agent: type[MedicalAgent] = MedicalAgent,
) -> tuple[int, dict]:
    monkeypatch.setattr("app.api.routes.incidents.get_incident_agent", agent)
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "生病去看醫生"}
    )
    assert created.status_code == 201, created.text
    incident_id = created.json()["incident"]["incident_id"]
    answered = await client.post(
        f"/incidents/{incident_id}/messages", json={"content": "生病"}
    )
    state = (await client.get(f"/incidents/{incident_id}")).json()
    return answered.status_code, state


async def test_平台不拒收沒有列在事故類型保障裡的險種結論(
    client: AsyncClient, chubb_policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, state = await run(client, chubb_policy, monkeypatch)

    assert status == 200
    assert state["incident_type_code"] == "medical"


async def test_平台照常建立就醫的待辦(
    client: AsyncClient, chubb_policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, state = await run(client, chubb_policy, monkeypatch)

    codes = {t["document_code"] for t in state["todos"]}
    # 診斷書、醫療費用收據正本、受益人身分證明、保險單；住院證明的條件是 hosp＝是，這次沒住院
    assert {"D13", "D14", "D24", "D25"} <= codes
    assert "D15" not in codes
    assert "D10" in codes  # 理賠申請書（行程共用）


async def test_理賠頁的可能適用項目看得到這一筆(
    client: AsyncClient, chubb_policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, state = await run(client, chubb_policy, monkeypatch)

    # 理賠頁（IncidentCard）依 ctx.clauses 的結論分組，不再用事故類型的保障過濾
    applicable = [c for c in state["clauses"] if c["conclusion"] == "applicable"]
    assert [(c["insurance_code"], c["section"], c["reason"]) for c in applicable] == [
        ("CHUBB04", None, REASON)
    ]
    unsure = {
        c["insurance_code"]
        for c in state["clauses"]
        if c["conclusion"] == "insufficient"
    }
    assert unsure == {"CHUBB01", "CHUBB02", "CHUBB03"}


async def test_對照_保單沒有的險種還是被擋下_不建立待辦(
    client: AsyncClient, chubb_policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    status, state = await run(client, chubb_policy, monkeypatch, StrangerInsuranceAgent)

    assert status == 502  # 違反契約：clauses 含有保單沒有涵蓋的保障
    assert state["todos"] == []
    # 建立事件時平台就列出保單涵蓋的保障（理由是「保單涵蓋」）；被擋下的回覆不會寫進任何結論
    assert {c["insurance_code"] for c in state["clauses"]} == {
        "CHUBB01",
        "CHUBB02",
        "CHUBB03",
        "CHUBB04",
    }
    assert {c["reason"] for c in state["clauses"]} == {"保單涵蓋"}

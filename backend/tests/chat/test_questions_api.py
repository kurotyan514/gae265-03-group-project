"""1-4 方案問答（spec #120）：改寫、Jev guardrail、兩個方案各自檢索、數字白名單，不存檔。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.api.routes.conversations import answer_model
from app.api.routes.questions import question_guard
from app.domain import questions
from app.domain.chat import ORIGINAL_ONLY_NOTICE
from app.domain.questions import NOT_COVERED, OUT_OF_SCOPE
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import Comparison, Conversation, Message, User
from app.seed import load_plan_data
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_typesafe import ClassifierResponse, NoulAnswer
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

TODAY = datetime.now(ZoneInfo("Asia/Taipei")).date()
# 6 天、班機延誤優先：推薦 fubon_advanced、次推薦 huanan_basic
TRIP = {
    "destination": "日本",
    "depart_date": (TODAY + timedelta(days=1)).isoformat(),
    "return_date": (TODAY + timedelta(days=6)).isoformat(),
    "age": 30,
    "concerns": ["班機延誤", "突然生病就醫"],
}
ASK = "傷害醫療保險金怎麼申請？"  # 條文有這些字，關鍵字檢索一定命中
NO_MATCH = "xyzzy"

pytestmark = pytest.mark.usefixtures("user", "plan_data")


class FakeModel:
    """依序回覆的 chat model，記下每次收到的訊息。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[list] = []

    def __call__(self, messages):
        self.calls.append(messages)
        return AIMessage(self.replies.pop(0))


class FakeGuard:
    def __init__(self, related: float = 0.9, injection: float = 0.1) -> None:
        self.nouls = {"related": related, "injection": injection}
        self.requests: list[dict] = []

    def __call__(self, request):
        self.requests.append(request)
        return ClassifierResponse(
            model="fake",
            answers={k: NoulAnswer(type="noul", noul=v) for k, v in self.nouls.items()},
        )


def use(model: FakeModel | None = None, guard: FakeGuard | None = None) -> None:
    if model is not None:
        app.dependency_overrides[answer_model] = lambda: RunnableLambda(model)
    if guard is not None:
        app.dependency_overrides[question_guard] = lambda: RunnableLambda(guard)


@pytest.fixture(autouse=True)
def reset_fakes():
    use(FakeModel(), FakeGuard())
    yield
    app.dependency_overrides.pop(answer_model, None)
    app.dependency_overrides.pop(question_guard, None)


@pytest.fixture
async def plan_data(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())


@pytest.fixture
async def comparison_id(client: AsyncClient) -> str:
    r = await client.post("/comparisons", json=TRIP)
    assert r.status_code == 201, r.text
    rec = r.json()["recommendation"]
    assert (rec["recommended"]["plan_code"], rec["alternative"]["plan_code"]) == (
        "fubon_advanced",
        "huanan_basic",
    )
    return r.json()["id"]


async def ask(client: AsyncClient, cid: str, question: str, history=()) -> dict:
    r = await client.post(
        f"/comparisons/{cid}/questions",
        json={"question": question, "history": list(history)},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def searches(monkeypatch) -> list[tuple[str, list[str]]]:
    calls: list[tuple[str, list[str]]] = []
    real = questions.search_rules

    async def spy(session, query, **kw):
        calls.append((query, kw["insurance_codes"]))
        return await real(session, query, **kw)

    monkeypatch.setattr(questions, "search_rules", spy)
    return calls


@pytest.mark.usefixtures("catalog_loaded")
async def test_answer_cites_both_plans_by_their_own_insurances(
    client: AsyncClient, comparison_id: str, searches
) -> None:
    model = FakeModel("兩個方案都可能適用，申請方式請看下方條文。")
    use(model)

    body = await ask(client, comparison_id, ASK)

    assert body["answer"] == "兩個方案都可能適用，申請方式請看下方條文。"
    assert body["original_only"] is False
    assert [(g["plan_code"], g["recommended"]) for g in body["citations"]] == [
        ("fubon_advanced", True),
        ("huanan_basic", False),
    ]
    fubon, huanan = body["citations"]
    assert fubon["citations"] and all(
        c["insurance_code"].startswith("FUBON") for c in fubon["citations"]
    )
    assert huanan["citations"] and all(
        c["insurance_code"].startswith("HUANAN") for c in huanan["citations"]
    )
    assert searches == [
        (ASK, ["FUBON01", "FUBON02", "FUBON03", "FUBON04", "FUBON05", "FUBON06"]),
        (ASK, [f"HUANAN0{i}" for i in range(1, 8)]),
    ]
    # 沒有 history 不改寫：只呼叫一次（回答）
    assert len(model.calls) == 1


@pytest.mark.usefixtures("catalog_loaded")
async def test_history_is_rewritten_before_guard_and_search(
    client: AsyncClient, comparison_id: str, searches
) -> None:
    rewritten = "次推薦方案的傷害醫療保險金怎麼申請？"
    model = FakeModel(rewritten, "次推薦要檢附收據申請。")
    guard = FakeGuard()
    use(model, guard)

    body = await ask(
        client,
        comparison_id,
        "那次推薦呢？",
        [{"question": ASK, "answer": "推薦方案要檢附收據申請。"}],
    )

    assert body["answer"] == "次推薦要檢附收據申請。"
    assert [q for q, _ in searches] == [rewritten, rewritten]
    assert guard.requests[0]["state"]["question"] == rewritten
    # 改寫時看得到前文
    assert any("推薦方案要檢附收據申請。" in str(m.content) for m in model.calls[0])


@pytest.mark.parametrize(("related", "injection"), [(0.1, 0.1), (0.9, 0.9)])
async def test_guard_blocks_without_search_or_answer(
    client: AsyncClient, comparison_id: str, searches, related, injection
) -> None:
    model = FakeModel()  # 沒有回覆可用：被呼叫就會失敗
    use(model, FakeGuard(related, injection))

    body = await ask(client, comparison_id, "今天天氣如何？")

    assert body == {"answer": OUT_OF_SCOPE, "original_only": False, "citations": []}
    assert searches == []
    assert model.calls == []


@pytest.mark.usefixtures("catalog_loaded")
async def test_guard_thresholds_are_exclusive(
    client: AsyncClient, comparison_id: str
) -> None:
    use(FakeModel("請看下方條文。"), FakeGuard(related=0.2, injection=0.8))
    assert (await ask(client, comparison_id, ASK))["answer"] == "請看下方條文。"


@pytest.mark.usefixtures("catalog_loaded")
async def test_nothing_relevant_in_either_plan_is_not_covered(
    client: AsyncClient, comparison_id: str
) -> None:
    model = FakeModel()
    use(model)

    body = await ask(client, comparison_id, NO_MATCH)

    assert body == {"answer": NOT_COVERED, "original_only": False, "citations": []}
    assert model.calls == []


@pytest.mark.usefixtures("catalog_loaded")
async def test_amount_from_plan_benefits_passes_whitelist(
    client: AsyncClient, comparison_id: str
) -> None:
    # fubon_advanced 推薦保額（600 萬）下的保障明細
    use(FakeModel("推薦方案的海外突發疾病住院醫療最高 480,000 元。"))
    body = await ask(client, comparison_id, ASK)
    assert body["original_only"] is False
    assert body["answer"] == "推薦方案的海外突發疾病住院醫療最高 480,000 元。"


@pytest.mark.usefixtures("catalog_loaded")
async def test_card_sum_without_quote_uses_recommended_sum_like_scenarios(
    client: AsyncClient, comparison_id: str, session: AsyncSession
) -> None:
    # 試算表換版後存下的保額沒有報價：跟 1-3、情境試算一樣回到推薦保額的保障明細
    comparison = await session.get(Comparison, comparison_id)
    assert comparison is not None
    comparison.recommended_sum_insured = 1
    session.add(comparison)
    await session.commit()

    use(FakeModel("推薦方案的海外突發疾病住院醫療最高 480,000 元。"))
    body = await ask(client, comparison_id, ASK)
    assert body["original_only"] is False


@pytest.mark.usefixtures("catalog_loaded")
async def test_unsupported_number_falls_back_to_original_text(
    client: AsyncClient, comparison_id: str
) -> None:
    use(FakeModel("最高可給付 9,876,543 元。"))
    body = await ask(client, comparison_id, ASK)
    assert body["original_only"] is True
    assert body["answer"].startswith(ORIGINAL_ONLY_NOTICE)
    assert "9876543" not in body["answer"].replace(",", "")
    cited = body["citations"][0]["citations"][0]
    assert cited["excerpt"] in body["answer"]


@pytest.mark.usefixtures("catalog_loaded")
async def test_number_only_in_history_does_not_pass(
    client: AsyncClient, comparison_id: str
) -> None:
    use(FakeModel(ASK, "跟前面說的一樣，最高 7,654,321 元。"))
    body = await ask(
        client,
        comparison_id,
        "那怎麼申請？",
        [{"question": "最高賠多少？", "answer": "最高 7,654,321 元。"}],
    )
    assert body["original_only"] is True


@pytest.mark.usefixtures("catalog_loaded")
async def test_llm_failure_falls_back_to_original_text(
    client: AsyncClient, comparison_id: str
) -> None:
    def boom(_):
        raise RuntimeError("provider down")

    app.dependency_overrides[answer_model] = lambda: RunnableLambda(boom)
    body = await ask(client, comparison_id, ASK)
    assert body["original_only"] is True
    assert body["citations"]


@pytest.mark.usefixtures("catalog_loaded")
async def test_nothing_is_stored(
    client: AsyncClient, comparison_id: str, session: AsyncSession
) -> None:
    use(FakeModel("請看下方條文。"))
    before = await session.get(Comparison, comparison_id)
    assert before is not None
    updated_at = before.updated_at

    await ask(client, comparison_id, ASK)

    for table in (Conversation, Message):
        assert (await session.exec(select(func.count()).select_from(table))).one() == 0
    session.expire_all()
    after = await session.get(Comparison, comparison_id)
    assert after is not None and after.updated_at == updated_at


@pytest.mark.parametrize(
    "body",
    [
        {"question": "x" * 301},
        {"question": "   "},
        {"question": ASK, "history": [{"question": "q", "answer": "a"}] * 4},
    ],
)
async def test_invalid_request_is_422(
    client: AsyncClient, comparison_id: str, body: dict
) -> None:
    r = await client.post(f"/comparisons/{comparison_id}/questions", json=body)
    assert r.status_code == 422


async def test_other_users_comparison_is_404(
    client: AsyncClient, comparison_id: str, other_user: User
) -> None:
    app.dependency_overrides[current_user] = lambda: other_user

    r = await client.post(
        f"/comparisons/{comparison_id}/questions", json={"question": ASK}
    )
    assert r.status_code == 404


async def test_without_recommendation_is_422(client: AsyncClient) -> None:
    r = await client.post("/comparisons", json=TRIP | {"concerns": []})
    r = await client.post(
        f"/comparisons/{r.json()['id']}/questions", json={"question": ASK}
    )
    assert r.status_code == 422

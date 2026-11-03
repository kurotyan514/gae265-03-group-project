"""對話端點：列出對話、取得歷史、送出訊息（ADR-0010／0013：只用對話綁的險種條文，不串流）。"""

import logging
import uuid

import pytest
from app.api.deps import current_user
from app.api.routes.conversations import answer_model
from app.domain.chat import NOT_COVERED, ORIGINAL_ONLY_NOTICE
from app.main import app
from app.models import Conversation, Message, MessageCitation, User
from httpx import AsyncClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# 條文裡有這些字，關鍵字檢索一定命中
ASK = "傷害醫療保險金怎麼申請？"
NO_MATCH = "xyzzy"  # 條款庫裡沒有、向量也不會相近


def use_model(*responses: str) -> None:
    app.dependency_overrides[answer_model] = lambda: FakeListChatModel(
        responses=list(responses)
    )


@pytest.fixture(autouse=True)
def reset_model():
    yield
    app.dependency_overrides.pop(answer_model, None)


async def new_conversation(client: AsyncClient) -> str:
    response = await client.post("/plans/taian/conversations")
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_answer_comes_with_citations(client: AsyncClient) -> None:
    use_model("需要在事故發生後向保險公司提出申請，細節請看下方條文。")
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": ASK}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role"] == "assistant"
    assert body["content"] == "需要在事故發生後向保險公司提出申請，細節請看下方條文。"
    assert body["citations"]
    first = body["citations"][0]
    assert first["insurance_code"].startswith("TAIAN")
    assert first["article_no"] >= 1
    assert first["page_start"] >= 1
    assert first["excerpt"]


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_history_has_both_sides_in_order(client: AsyncClient) -> None:
    use_model("請看下方條文。")
    cid = await new_conversation(client)
    await client.post(f"/conversations/{cid}/messages", json={"content": ASK})

    response = await client.get(f"/conversations/{cid}/messages")

    assert response.status_code == 200
    messages = response.json()
    assert [(m["seq"], m["role"]) for m in messages] == [(1, "user"), (2, "assistant")]
    assert messages[0]["content"] == ASK
    assert messages[0]["citations"] == []
    assert messages[1]["citations"]


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_number_not_in_source_falls_back_to_original_text(
    client: AsyncClient,
) -> None:
    use_model("最高可給付 9,876,543 元。")
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": ASK}
    )

    body = response.json()
    assert "9876543" not in body["content"].replace(",", "")
    assert body["content"].startswith(ORIGINAL_ONLY_NOTICE)
    cited = body["citations"][0]
    assert cited["excerpt"] in body["content"]
    assert f"第 {cited['article_no']} 條" in body["content"]
    assert f"第 {cited['page_start']} 頁" in body["content"]


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_llm_failure_falls_back_to_original_text(client: AsyncClient) -> None:
    def boom(_):
        raise RuntimeError("provider down")

    app.dependency_overrides[answer_model] = lambda: RunnableLambda(boom)
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": ASK}
    )

    assert response.status_code == 200
    assert response.json()["content"].startswith(ORIGINAL_ONLY_NOTICE)
    assert response.json()["citations"]


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_nothing_relevant_says_not_covered_without_asking_llm(
    client: AsyncClient,
) -> None:
    def must_not_run(_):
        raise AssertionError("沒有相關條文時不該呼叫 LLM")

    app.dependency_overrides[answer_model] = lambda: RunnableLambda(must_not_run)
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": NO_MATCH}
    )

    body = response.json()
    assert body["content"] == NOT_COVERED
    assert body["citations"] == []


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_llm_saying_not_covered_is_not_covered(client: AsyncClient) -> None:
    use_model("NOT_COVERED")
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": ASK}
    )

    body = response.json()
    assert body["content"] == NOT_COVERED
    assert body["citations"] == []


@pytest.mark.usefixtures("catalog_loaded")
async def test_conversation_without_insurances_is_not_covered(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    conversation = Conversation(user_id=user.id, title="空")
    session.add(conversation)
    await session.commit()

    response = await client.post(
        f"/conversations/{conversation.id}/messages", json={"content": ASK}
    )

    assert response.status_code == 200
    assert response.json()["content"] == NOT_COVERED


@pytest.mark.usefixtures("catalog_loaded", "user")
@pytest.mark.parametrize("content", ["", "   ", "x" * 1001])
async def test_invalid_content_is_422(client: AsyncClient, content: str) -> None:
    cid = await new_conversation(client)
    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": content}
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_messages_are_persisted_with_citations(
    client: AsyncClient, session: AsyncSession
) -> None:
    use_model("請看下方條文。")
    cid = await new_conversation(client)
    sent = await client.post(f"/conversations/{cid}/messages", json={"content": ASK})

    rows = (
        await session.exec(
            select(Message).where(Message.conversation_id == uuid.UUID(cid))
        )
    ).all()
    assert [r.role for r in sorted(rows, key=lambda r: r.seq)] == ["user", "assistant"]
    citations = (
        await session.exec(
            select(MessageCitation).where(
                MessageCitation.message_id == uuid.UUID(sent.json()["id"])
            )
        )
    ).all()
    assert len(citations) == len(sent.json()["citations"]) > 0


@pytest.mark.usefixtures("catalog_loaded")
async def test_list_conversations_only_mine(
    client: AsyncClient, user: User, other_user: User
) -> None:
    mine = await new_conversation(client)
    app.dependency_overrides[current_user] = lambda: other_user
    theirs = await new_conversation(client)

    listed = await client.get("/conversations")
    assert [c["id"] for c in listed.json()] == [theirs]

    app.dependency_overrides[current_user] = lambda: user
    listed = await client.get("/conversations")
    assert [c["id"] for c in listed.json()] == [mine]
    assert listed.json()[0]["insurance_codes"] == ["TAIAN01", "TAIAN02", "TAIAN03"]


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_other_users_conversation_is_404(
    client: AsyncClient, other_user: User
) -> None:
    use_model("請看下方條文。")
    cid = await new_conversation(client)
    await client.post(f"/conversations/{cid}/messages", json={"content": ASK})

    app.dependency_overrides[current_user] = lambda: other_user
    assert (await client.get(f"/conversations/{cid}/messages")).status_code == 404
    sent = await client.post(f"/conversations/{cid}/messages", json={"content": ASK})
    assert sent.status_code == 404


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_unknown_conversation_is_404(client: AsyncClient) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/conversations/{missing}/messages")).status_code == 404
    sent = await client.post(
        f"/conversations/{missing}/messages", json={"content": ASK}
    )
    assert sent.status_code == 404


async def test_requires_login(client: AsyncClient) -> None:
    cid = uuid.uuid4()
    assert (await client.get("/conversations")).status_code == 401
    assert (await client.get(f"/conversations/{cid}/messages")).status_code == 401
    sent = await client.post(f"/conversations/{cid}/messages", json={"content": ASK})
    assert sent.status_code == 401


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_user_input_is_not_logged(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "我的護照號碼是秘密ZXQ123"

    def boom(_):
        raise RuntimeError(f"provider echoed: {secret}")

    app.dependency_overrides[answer_model] = lambda: RunnableLambda(boom)
    cid = await new_conversation(client)

    with caplog.at_level(logging.DEBUG):
        await client.post(
            f"/conversations/{cid}/messages", json={"content": f"{ASK}{secret}"}
        )

    assert secret not in caplog.text


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_answer_may_cite_article_number(client: AsyncClient) -> None:
    import re

    from langchain_core.messages import AIMessage

    def cite_first_article(messages):
        article = re.search(r"第 (\d+) 條", messages[0].content).group(1)  # pyright: ignore[reportOptionalMemberAccess]
        return AIMessage(f"依第 {article} 條的約定辦理。")

    app.dependency_overrides[answer_model] = lambda: RunnableLambda(cite_first_article)
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": ASK}
    )

    assert response.json()["content"].startswith("依第 ")


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_not_covered_marker_with_trailing_text(client: AsyncClient) -> None:
    use_model("NOT_COVERED。原文沒有提到")
    cid = await new_conversation(client)

    response = await client.post(
        f"/conversations/{cid}/messages", json={"content": ASK}
    )

    assert response.json()["content"] == NOT_COVERED


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_failed_answer_leaves_no_orphan_question(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_search(*_args, **_kwargs):
        raise RuntimeError("embedding down")

    monkeypatch.setattr("app.domain.chat.answer.search_rules", broken_search)
    cid = await new_conversation(client)

    with pytest.raises(RuntimeError):
        await client.post(f"/conversations/{cid}/messages", json={"content": ASK})

    rows = (await session.exec(select(Message))).all()
    assert rows == []

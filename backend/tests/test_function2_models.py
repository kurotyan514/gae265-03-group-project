"""功能二的資料表：連動刪除、使用者一致性、唯一性與擴充項目必須有出處。"""

import uuid

import pytest
from app.core.config import settings
from app.models import (
    ChecklistItem,
    ClaimCase,
    ClaimDocument,
    ClaimSubmission,
    Conversation,
    ConversationInsurance,
    Insurance,
    Message,
    Policy,
    PolicyChunk,
    PolicyChunkEmbedding,
    PolicyEvent,
    PolicyInsurance,
    User,
    conversation_has_source,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, func
from sqlmodel import select as sm_select
from sqlmodel.ext.asyncio.session import AsyncSession

MODEL = "text-embedding-3-large"

# 使用者擁有的所有資料表；刪除使用者後這些都必須是空的
OWNED_TABLES: list[type[SQLModel]] = [
    Policy,
    PolicyInsurance,
    PolicyChunk,
    PolicyChunkEmbedding,
    PolicyEvent,
    Conversation,
    ConversationInsurance,
    Message,
    ClaimCase,
    ChecklistItem,
    ClaimDocument,
    ClaimSubmission,
]


async def count(session: AsyncSession, model: type[SQLModel]) -> int:
    return (await session.exec(sm_select(func.count()).select_from(model))).one()


async def add_user(session: AsyncSession, sub: str = "g-1") -> User:
    user = User(google_sub=sub, email=f"{sub}@example.com", name="測試使用者")
    session.add(user)
    await session.commit()
    return user


async def add_policy(session: AsyncSession, user: User) -> Policy:
    policy = Policy(user_id=user.id, display_name="保單 1")
    session.add(policy)
    await session.commit()
    return policy


async def add_chunk(
    session: AsyncSession,
    policy: Policy,
    idx: int = 0,
    user_id: uuid.UUID | None = None,
) -> PolicyChunk:
    chunk = PolicyChunk(
        policy_id=policy.id,
        user_id=user_id or policy.user_id,
        idx=idx,
        page_start=1,
        page_end=1,
        content="第一條　保險範圍…",
    )
    session.add(chunk)
    await session.commit()
    return chunk


async def add_conversation(
    session: AsyncSession, user: User, policy: Policy | None = None
) -> Conversation:
    conversation = Conversation(
        user_id=user.id, policy_id=policy.id if policy else None, title="問答"
    )
    session.add(conversation)
    await session.commit()
    return conversation


async def add_case(
    session: AsyncSession, user: User, conversation: Conversation
) -> ClaimCase:
    case = ClaimCase(
        user_id=user.id, conversation_id=conversation.id, incident_type="baggage"
    )
    session.add(case)
    await session.commit()
    return case


async def build_everything(session: AsyncSession, user: User) -> Policy:
    """替一個使用者建立所有相關資料表各一列，回傳他的保單。"""
    insurance = Insurance(code="T068", name="旅行平安保險")
    session.add(insurance)
    await session.commit()

    policy = await add_policy(session, user)
    chunk = await add_chunk(session, policy)
    session.add_all(
        [
            PolicyInsurance(policy_id=policy.id, insurance_id=insurance.id),
            PolicyChunkEmbedding(
                chunk_id=chunk.id,
                model=MODEL,
                embedding=[0.1] * settings.EMBEDDING_DIMENSIONS,
            ),
            PolicyEvent(
                policy_id=policy.id, seq=1, step="extract", status="ok", message="讀取"
            ),
        ]
    )
    conversation = await add_conversation(session, user, policy)
    plan_conversation = await add_conversation(session, user)
    session.add_all(
        [
            ConversationInsurance(
                conversation_id=plan_conversation.id, insurance_id=insurance.id
            ),
            Message(conversation_id=conversation.id, seq=1, role="user", content="Q"),
        ]
    )
    case = await add_case(session, user, conversation)
    item = ChecklistItem(claim_case_id=case.id, label="理賠申請書", kind="basic")
    session.add(item)
    await session.commit()
    session.add_all(
        [
            ClaimDocument(claim_case_id=case.id, checklist_item_id=item.id),
            ClaimSubmission(claim_case_id=case.id),
        ]
    )
    await session.commit()
    return policy


async def test_deleting_a_user_removes_all_their_data(session: AsyncSession) -> None:
    user = await add_user(session)
    await build_everything(session, user)
    for model in OWNED_TABLES:
        assert await count(session, model) >= 1, model.__name__

    await session.delete(user)
    await session.commit()

    for model in OWNED_TABLES:
        assert await count(session, model) == 0, model.__name__
    # 險種是所有人共用的知識，不受影響
    assert await count(session, Insurance) == 1


async def test_deleting_a_user_keeps_other_users_data(session: AsyncSession) -> None:
    mine = await add_user(session, "g-1")
    other = await add_user(session, "g-2")
    await build_everything(session, mine)
    other_policy = await add_policy(session, other)
    await add_chunk(session, other_policy)

    await session.delete(mine)
    await session.commit()

    assert await count(session, User) == 1
    assert await count(session, Policy) == 1
    assert await count(session, PolicyChunk) == 1


async def test_deleting_a_policy_removes_its_chunks_and_conversations(
    session: AsyncSession,
) -> None:
    user = await add_user(session)
    policy = await build_everything(session, user)

    await session.delete(policy)
    await session.commit()

    for model in (
        Policy,
        PolicyInsurance,
        PolicyChunk,
        PolicyChunkEmbedding,
        PolicyEvent,
        Message,
        ClaimCase,
        ChecklistItem,
        ClaimDocument,
        ClaimSubmission,
    ):
        assert await count(session, model) == 0, model.__name__
    # 綁保單的對話跟著消失；選保單那條路的對話與使用者本人不受影響
    assert await count(session, Conversation) == 1
    assert await count(session, ConversationInsurance) == 1
    assert await count(session, User) == 1


async def test_chunk_user_must_match_the_policy_owner(session: AsyncSession) -> None:
    owner = await add_user(session, "g-1")
    other = await add_user(session, "g-2")
    policy = await add_policy(session, owner)

    with pytest.raises(IntegrityError):
        await add_chunk(session, policy, user_id=other.id)


async def test_conversation_policy_must_belong_to_the_same_user(
    session: AsyncSession,
) -> None:
    owner = await add_user(session, "g-1")
    other = await add_user(session, "g-2")
    policy = await add_policy(session, owner)

    with pytest.raises(IntegrityError):
        await add_conversation(session, other, policy)


async def test_claim_case_conversation_must_belong_to_the_same_user(
    session: AsyncSession,
) -> None:
    owner = await add_user(session, "g-1")
    other = await add_user(session, "g-2")
    conversation = await add_conversation(
        session, owner, await add_policy(session, owner)
    )

    with pytest.raises(IntegrityError):
        await add_case(session, other, conversation)


async def test_google_sub_is_unique(session: AsyncSession) -> None:
    await add_user(session, "g-1")
    session.add(User(google_sub="g-1", email="x@example.com"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_chunk_index_is_unique_within_a_policy(session: AsyncSession) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    other_policy = await add_policy(session, user)
    await add_chunk(session, policy, 0)
    await add_chunk(session, other_policy, 0)  # 不同保單可以有同樣的 idx

    with pytest.raises(IntegrityError):
        await add_chunk(session, policy, 0)


async def test_embedding_is_unique_per_chunk_and_model(session: AsyncSession) -> None:
    user = await add_user(session)
    chunk = await add_chunk(session, await add_policy(session, user))
    vector = [0.1] * settings.EMBEDDING_DIMENSIONS
    session.add_all(
        [
            PolicyChunkEmbedding(chunk_id=chunk.id, model=MODEL, embedding=vector),
            PolicyChunkEmbedding(chunk_id=chunk.id, model="bge-m3", embedding=vector),
        ]
    )
    await session.commit()

    session.add(PolicyChunkEmbedding(chunk_id=chunk.id, model=MODEL, embedding=vector))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_message_and_event_seq_are_unique(session: AsyncSession) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    conversation = await add_conversation(session, user, policy)
    # rollback 之後物件的屬性會過期，先把 id 取出來
    policy_id, conversation_id = policy.id, conversation.id
    session.add(
        Message(conversation_id=conversation_id, seq=1, role="user", content="Q")
    )
    session.add(
        PolicyEvent(
            policy_id=policy_id, seq=1, step="extract", status="ok", message="m"
        )
    )
    await session.commit()

    session.add(
        Message(conversation_id=conversation_id, seq=1, role="assistant", content="A")
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
    session.add(
        PolicyEvent(policy_id=policy_id, seq=1, step="chunk", status="ok", message="m")
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_policy_insurance_is_unique(session: AsyncSession) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    insurance = Insurance(code="T068", name="旅行平安保險")
    session.add(insurance)
    await session.commit()
    session.add(PolicyInsurance(policy_id=policy.id, insurance_id=insurance.id))
    await session.commit()

    session.add(PolicyInsurance(policy_id=policy.id, insurance_id=insurance.id))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_new_policy_has_no_stored_original(session: AsyncSession) -> None:
    policy = await add_policy(session, await add_user(session))
    assert policy.status == "processing"
    assert policy.storage_provider is None
    assert policy.storage_ref is None


async def test_extended_checklist_item_requires_a_citation(
    session: AsyncSession,
) -> None:
    user = await add_user(session)
    conversation = await add_conversation(
        session, user, await add_policy(session, user)
    )
    case = await add_case(session, user, conversation)

    # 基本款不需要出處
    session.add(ChecklistItem(claim_case_id=case.id, label="理賠申請書", kind="basic"))
    # 擴充項目有出處才行
    session.add(
        ChecklistItem(
            claim_case_id=case.id,
            label="警方報案證明",
            kind="extended",
            citation={"source": "policy", "page": 3},
        )
    )
    await session.commit()
    assert await count(session, ChecklistItem) == 2

    session.add(ChecklistItem(claim_case_id=case.id, label="沒出處", kind="extended"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_conversation_needs_a_policy_or_an_insurance(
    session: AsyncSession,
) -> None:
    user = await add_user(session)
    insurance = Insurance(code="T068", name="旅行平安保險")
    session.add(insurance)
    await session.commit()

    unbound = await add_conversation(session, user)
    assert not await conversation_has_source(session, unbound)

    with_policy = await add_conversation(session, user, await add_policy(session, user))
    assert await conversation_has_source(session, with_policy)

    with_insurance = await add_conversation(session, user)
    session.add(
        ConversationInsurance(
            conversation_id=with_insurance.id, insurance_id=insurance.id
        )
    )
    await session.commit()
    assert await conversation_has_source(session, with_insurance)

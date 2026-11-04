"""功能二的資料表：連動刪除、使用者一致性、唯一性與擴充項目必須有出處。"""

import pytest
from app.models import (
    Conversation,
    ConversationInsurance,
    Incident,
    IncidentDocument,
    IncidentFact,
    IncidentTodo,
    Insurance,
    Message,
    Policy,
    PolicyAddon,
    PolicySubmission,
    User,
    conversation_has_source,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, func
from sqlmodel import select as sm_select
from sqlmodel.ext.asyncio.session import AsyncSession

# 使用者擁有的所有資料表；刪除使用者後這些都必須是空的
OWNED_TABLES: list[type[SQLModel]] = [
    Policy,
    PolicyAddon,
    Conversation,
    ConversationInsurance,
    Message,
    Incident,
    IncidentFact,
    IncidentTodo,
    IncidentDocument,
    PolicySubmission,
]


async def count(session: AsyncSession, model: type[SQLModel]) -> int:
    return (await session.exec(sm_select(func.count()).select_from(model))).one()


async def add_user(session: AsyncSession, sub: str = "g-1") -> User:
    user = User(email=f"{sub}@example.com", name="測試使用者")
    session.add(user)
    await session.commit()
    return user


async def add_policy(session: AsyncSession, user: User) -> Policy:
    policy = Policy(user_id=user.id, display_name="保單 1", plan_id="fubon_general")
    session.add(policy)
    await session.commit()
    return policy


async def add_conversation(
    session: AsyncSession, user: User, policy: Policy | None = None
) -> Conversation:
    conversation = Conversation(
        user_id=user.id, policy_id=policy.id if policy else None, title="問答"
    )
    session.add(conversation)
    await session.commit()
    return conversation


async def add_incident(session: AsyncSession, policy: Policy) -> Incident:
    incident = Incident(policy_id=policy.id, title="班機取消", description="班機取消了")
    session.add(incident)
    await session.commit()
    return incident


async def build_everything(session: AsyncSession, user: User) -> Policy:
    """替一個使用者建立所有相關資料表各一列，回傳他的保單。"""
    insurance = Insurance(code="T068", name="旅行平安保險")
    session.add(insurance)
    await session.commit()

    policy = await add_policy(session, user)
    session.add(PolicyAddon(policy_id=policy.id, insurance_id=insurance.id))
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
    incident = await add_incident(session, policy)
    todo = IncidentTodo(incident_id=incident.id, phase="on_site", title="取得證明")
    session.add(todo)
    await session.commit()
    session.add_all(
        [
            IncidentFact(
                incident_id=incident.id, fact_key="what", label="經過", value="班機取消"
            ),
            IncidentDocument(
                incident_id=incident.id,
                incident_todo_id=todo.id,
                file_name="a.pdf",
                size_bytes=1,
                storage_path="x",
                content_type="application/pdf",
            ),
            PolicySubmission(policy_id=incident.policy_id),
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
    await add_policy(session, other)

    await session.delete(mine)
    await session.commit()

    assert await count(session, User) == 1
    assert await count(session, Policy) == 1


async def test_deleting_a_policy_removes_its_insurances_and_conversations(
    session: AsyncSession,
) -> None:
    user = await add_user(session)
    policy = await build_everything(session, user)

    await session.delete(policy)
    await session.commit()

    for model in (
        Policy,
        PolicyAddon,
        Message,
        Incident,
        IncidentFact,
        IncidentTodo,
        IncidentDocument,
        PolicySubmission,
    ):
        assert await count(session, model) == 0, model.__name__
    # 綁保單的對話跟著消失；選保單那條路的對話與使用者本人不受影響
    assert await count(session, Conversation) == 1
    assert await count(session, ConversationInsurance) == 1
    assert await count(session, User) == 1


async def test_conversation_policy_must_belong_to_the_same_user(
    session: AsyncSession,
) -> None:
    owner = await add_user(session, "g-1")
    other = await add_user(session, "g-2")
    policy = await add_policy(session, owner)

    with pytest.raises(IntegrityError):
        await add_conversation(session, other, policy)


async def test_incident_qa_conversation_must_have_an_incident(
    session: AsyncSession,
) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    incident = await add_incident(session, policy)
    user_id, policy_id, incident_id = user.id, policy.id, incident.id

    session.add(Conversation(user_id=user_id, policy_id=policy_id, kind="incident_qa"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    session.add(
        Conversation(
            user_id=user_id,
            policy_id=policy_id,
            kind="plan_qa",
            incident_id=incident_id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    session.add(
        Conversation(
            user_id=user_id,
            policy_id=policy_id,
            kind="incident_qa",
            incident_id=incident_id,
        )
    )
    await session.commit()


async def test_message_seq_is_unique(session: AsyncSession) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    conversation = await add_conversation(session, user, policy)
    # rollback 之後物件的屬性會過期，先把 id 取出來
    conversation_id = conversation.id
    session.add(
        Message(conversation_id=conversation_id, seq=1, role="user", content="Q")
    )
    await session.commit()

    session.add(
        Message(conversation_id=conversation_id, seq=1, role="assistant", content="A")
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_policy_addon_is_unique(session: AsyncSession) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    insurance = Insurance(code="T068", name="旅行平安保險")
    session.add(insurance)
    await session.commit()
    # rollback 之後物件的屬性會過期，先把 id 取出來
    insurance_id, policy_id = insurance.id, policy.id
    session.add(PolicyAddon(policy_id=policy_id, insurance_id=insurance_id))
    await session.commit()

    session.add(PolicyAddon(policy_id=policy_id, insurance_id=insurance_id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    # 同一個險種可以加購不同的章，同一章不能重複
    session.add_all(
        [
            PolicyAddon(
                policy_id=policy_id, insurance_id=insurance_id, section="第二章"
            ),
            PolicyAddon(
                policy_id=policy_id, insurance_id=insurance_id, section="第三章"
            ),
        ]
    )
    await session.commit()
    session.add(
        PolicyAddon(policy_id=policy_id, insurance_id=insurance_id, section="第二章")
    )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_incident_constraints(session: AsyncSession) -> None:
    user = await add_user(session)
    incident = await add_incident(session, await add_policy(session, user))
    incident_id = incident.id

    session.add(IncidentTodo(incident_id=incident_id, phase="later", title="x"))
    with pytest.raises(IntegrityError):  # phase 只能是 on_site／after_return
        await session.commit()
    await session.rollback()

    session.add(
        IncidentTodo(incident_id=incident_id, phase="on_site", title="x", done_by="bot")
    )
    with pytest.raises(IntegrityError):  # done_by 只能是 user／agent
        await session.commit()
    await session.rollback()

    for key in ("a", "a"):  # 同事件內 fact_key 唯一
        session.add(
            IncidentFact(incident_id=incident_id, fact_key=key, label="l", value="v")
        )
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_deleting_an_incident_type_in_use_is_blocked(
    session: AsyncSession,
) -> None:
    from app.models import IncidentType

    user = await add_user(session)
    incident = await add_incident(session, await add_policy(session, user))
    itype = IncidentType(code="delay", name="班機延誤", follow_up_questions=[])
    session.add(itype)
    await session.commit()
    incident.incident_type_id = itype.id
    session.add(incident)
    await session.commit()

    await session.delete(itype)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


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


async def test_todo_status_owner_and_document_code_rules(
    session: AsyncSession,
) -> None:
    user = await add_user(session)
    policy = await add_policy(session, user)
    incident = await add_incident(session, policy)
    incident_id, policy_id = incident.id, policy.id

    def todo(**kw: object) -> IncidentTodo:
        return IncidentTodo(phase="on_site", title="x", **kw)  # pyright: ignore[reportArgumentType]

    session.add(todo(incident_id=incident_id, status="skipped"))
    with pytest.raises(IntegrityError):  # status 只能是 pending／done／not_applicable
        await session.commit()
    await session.rollback()

    session.add(todo())
    with pytest.raises(IntegrityError):  # 事件待辦或整個行程的待辦，要有一個擁有者
        await session.commit()
    await session.rollback()

    session.add(todo(incident_id=incident_id, policy_id=policy_id))
    with pytest.raises(IntegrityError):  # 不能同時屬於事件與行程
        await session.commit()
    await session.rollback()

    session.add(
        todo(policy_id=policy_id, document_code="D10")
    )  # 理賠申請書：整個行程一項
    await session.commit()
    session.add(todo(policy_id=policy_id, document_code="D10"))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    session.add(todo(incident_id=incident_id, document_code="D01"))
    await session.commit()
    session.add(todo(incident_id=incident_id, document_code="D01"))
    with pytest.raises(IntegrityError):  # 同事件內同一文件代碼只列一次
        await session.commit()


async def test_policy_progress_and_reminder_constraints(session: AsyncSession) -> None:
    user = await add_user(session)
    user_id = user.id

    def policy(**kw: object) -> Policy:
        return Policy(user_id=user_id, display_name="保單", plan_id="p", **kw)  # pyright: ignore[reportArgumentType]

    session.add(policy(last_step="2-3"))
    with pytest.raises(IntegrityError):  # 描述中只會停在 2-1 或 2-2
        await session.commit()
    await session.rollback()

    session.add(policy(reminder_count=4))
    with pytest.raises(IntegrityError):  # 提醒信最多 3 封
        await session.commit()

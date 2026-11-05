"""登入身分與 Google 授權：一人一筆、提供者帳號不重複、狀態受限制、刪除使用者時一併消失。"""

from datetime import UTC, datetime

import pytest
from app.models import GoogleGrant, Identity, Insurance, User
from app.seed import load_policy_codes
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession


async def add_user(session: AsyncSession, sub: str) -> User:
    user = User(email=f"{sub}@example.com")
    session.add(user)
    await session.commit()
    return user


def make_grant(
    user: User,
    status: str = "active",
    drive_folder_id: str | None = None,
) -> GoogleGrant:
    return GoogleGrant(
        user_id=user.id,
        scopes=["openid", "email"],
        refresh_token_encrypted=b"\x00\x01",
        granted_at=datetime.now(UTC),
        status=status,
        drive_folder_id=drive_folder_id,
    )


async def test_one_identity_per_user(session: AsyncSession) -> None:
    user = await add_user(session, "u1")
    session.add(Identity(user_id=user.id, provider="google", provider_user_id="s1"))
    await session.commit()
    session.add(Identity(user_id=user.id, provider="dev", provider_user_id="x"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_provider_account_cannot_be_shared(session: AsyncSession) -> None:
    a = await add_user(session, "u1")
    b = await add_user(session, "u2")
    session.add(Identity(user_id=a.id, provider="google", provider_user_id="same"))
    await session.commit()
    session.add(Identity(user_id=b.id, provider="google", provider_user_id="same"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_grant_is_one_per_user_and_status_is_limited(
    session: AsyncSession,
) -> None:
    user = await add_user(session, "u1")
    session.add(make_grant(user))
    await session.commit()
    session.add(make_grant(user))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()

    other = await add_user(session, "u2")
    session.add(make_grant(other, status="expired"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_user_removes_identity_and_grant(session: AsyncSession) -> None:
    user = await add_user(session, "u1")
    session.add(Identity(user_id=user.id, provider="google", provider_user_id="s1"))
    session.add(make_grant(user, drive_folder_id="folder"))
    await session.commit()
    await session.delete(user)
    await session.commit()
    for model in (Identity, GoogleGrant):
        assert (await session.exec(select(func.count()).select_from(model))).one() == 0


async def test_policy_codes_are_filled_from_config(session: AsyncSession) -> None:
    session.add(Insurance(code="FUBON01", name="旅行平安保險"))
    session.add(Insurance(code="FUBON99", name="沒有代碼的險種"))
    await session.commit()
    assert await load_policy_codes(session) >= 1
    await load_policy_codes(session)  # 重跑結果相同
    rows = {i.code: i for i in (await session.exec(select(Insurance))).all()}
    assert rows["FUBON01"].policy_codes["第二章 旅行平安保險"] == "T068"
    assert rows["FUBON99"].policy_codes == {}


async def test_revoked_grant_keeps_record_without_token(session: AsyncSession) -> None:
    user = await add_user(session, "u1")
    grant = make_grant(user)
    session.add(grant)
    await session.commit()
    grant.status = "revoked"
    grant.refresh_token_encrypted = None
    grant.revoked_at = datetime.now(UTC)
    session.add(grant)
    await session.commit()
    row = (await session.exec(select(GoogleGrant))).one()
    assert row.refresh_token_encrypted is None and row.status == "revoked"


async def test_incident_catalog_is_loaded_and_rerun_is_stable(
    session: AsyncSession,
) -> None:
    from app.models import IncidentType, TodoTemplate
    from app.seed import load_incident_catalog

    types, templates = await load_incident_catalog(session)
    assert types == 9  # 8 種事故類型 + 還沒判斷出類型時用的「其他」
    again = await load_incident_catalog(session)  # 重跑結果相同，不重複
    assert again == (types, templates)
    assert (
        await session.exec(select(func.count()).select_from(IncidentType))
    ).one() == 9
    count = (await session.exec(select(func.count()).select_from(TodoTemplate))).one()
    assert count == templates

    delay = (
        await session.exec(
            select(IncidentType).where(IncidentType.code == "flight_delay")
        )
    ).one()
    assert delay.item_keys == ["fdelay"]
    assert [f["key"] for f in delay.fields] == ["dep_plan", "dep_act", "reason"]
    docs = (
        await session.exec(
            select(TodoTemplate.document_code).where(
                TodoTemplate.incident_type_id == delay.id
            )
        )
    ).all()
    assert set(docs) == {"D01", "D02"}  # 班機延誤的條款沒有要求 D11，排除
    form = (
        await session.exec(
            select(TodoTemplate).where(col(TodoTemplate.incident_type_id).is_(None))
        )
    ).one()
    assert form.document_code == "D10" and form.is_claim_form

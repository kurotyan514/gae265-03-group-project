"""資料表統一基底，以及測試之間資料互不影響。"""

import uuid

from app.models import BaseTable
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession


# 只存在於測試：在 engine fixture 建 schema 前就註冊進 metadata
class Note(BaseTable, table=True):
    __tablename__ = "test_note"  # pyright: ignore[reportAssignmentType]

    body: str


async def test_base_table_has_uuid_id_and_utc_aware_timestamps(
    session: AsyncSession,
) -> None:
    note = Note(body="hi")
    session.add(note)
    await session.commit()
    await session.refresh(note)

    assert isinstance(note.id, uuid.UUID)
    assert note.created_at.tzinfo is not None
    assert note.created_at.utcoffset() is not None

    before = note.updated_at
    note.body = "changed"
    session.add(note)
    await session.commit()
    await session.refresh(note)
    assert note.updated_at > before


async def test_tables_are_empty_at_start_of_each_test_1(session: AsyncSession) -> None:
    assert await session.scalar(select(func.count()).select_from(Note)) == 0
    session.add(Note(body="leftover"))
    await session.commit()


async def test_tables_are_empty_at_start_of_each_test_2(session: AsyncSession) -> None:
    assert await session.scalar(select(func.count()).select_from(Note)) == 0
    session.add(Note(body="leftover"))
    await session.commit()

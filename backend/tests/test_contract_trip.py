"""契約 v2.13（ADR-0029）：行程 context、共同文件的資料表、行程版介面的假實作。"""

import uuid

import pytest
from app.contracts import (
    ClauseView,
    DocumentView,
    IncidentContext,
    PolicySummary,
    TodoView,
    TripClaimPackager,
    TripContext,
    TripDocumentDiscarder,
    TripDocumentRechecker,
    TripDocumentRecognizer,
    TripDocumentRenamer,
    UploadedFile,
    UserContext,
)
from app.contracts.fakes import FakeClaimPackager, FakeDocumentRecognizer
from app.models import (
    Incident,
    IncidentDocument,
    Policy,
    TodoTemplate,
    User,
)
from app.seed import load_incident_catalog
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

POLICY_ID = uuid.uuid4()
USER = UserContext(user_id=uuid.uuid4(), email="u@example.com")


class _NoGoogle:
    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None


def todo(title: str, incident_id: uuid.UUID | None, **kw: object) -> TodoView:
    return TodoView(
        id=uuid.uuid4(),
        incident_id=incident_id,
        phase="on_site",
        title=title,
        **kw,  # pyright: ignore[reportArgumentType]
    )


def incident(
    name: str, todos: list[TodoView], conclusion: str = "applicable"
) -> IncidentContext:
    clauses = [
        ClauseView(insurance_code="X", section="章", conclusion=conclusion)  # pyright: ignore[reportArgumentType]
    ]
    return IncidentContext(
        incident_id=todos[0].incident_id or uuid.uuid4(),
        title=name,
        description="",
        status="open",
        incident_type_name=name,
        policy=POLICY,
        clauses=clauses,
        covered=IncidentContext.is_covered(clauses),
        todos=todos,
    )


POLICY = PolicySummary(
    policy_id=POLICY_ID, plan_id="p", plan_name="方案", insurance_codes=[], coverages=[]
)


def make_trip() -> tuple[TripContext, TodoView, TodoView, TodoView, TodoView]:
    i1, i2 = uuid.uuid4(), uuid.uuid4()
    a = todo("班機延誤證明", i1)
    b = todo("行李遺失證明", i2)
    gone = todo("不符保障的待辦", uuid.uuid4())
    shared = todo("理賠申請書", None, scope="policy", document_code="D10")
    trip = TripContext(
        policy=POLICY,
        incidents=[
            incident("班機延誤", [a]),
            incident("行李遺失", [b]),
            incident("不符保障", [gone], conclusion="insufficient"),
        ],
        shared_todos=[shared],
    )
    return trip, a, b, gone, shared


def test_沒有條款結論算在保障內_要有一項可能適用才算涵蓋() -> None:
    def c(x: str) -> ClauseView:
        return ClauseView(insurance_code="X", conclusion=x)  # pyright: ignore[reportArgumentType]

    assert IncidentContext.is_covered([])
    assert IncidentContext.is_covered([c("excluded"), c("applicable")])
    assert not IncidentContext.is_covered([c("excluded"), c("insufficient")])


def test_交給_6_7_的行程濾掉不符保障的事件與不適用的待辦() -> None:
    trip, a, b, gone, shared = make_trip()
    trip.incidents[0].todos.append(todo("不適用", a.incident_id, applicable=False))
    seen = trip.for_agents_6_7()

    assert {t.id for t in seen.todos} == {a.id, b.id, shared.id}
    assert len(trip.incidents) == 3  # 原本的不動


def test_行程的待辦與文件含共同文件() -> None:
    trip, a, b, _, shared = make_trip()
    trip.shared_documents.append(
        DocumentView(
            id=uuid.uuid4(),
            todo_id=shared.id,
            file_name="x.pdf",
            content_type="application/pdf",
            storage_path="p",
            recognition_status="recognized",
        )
    )

    assert shared.id in {t.id for t in trip.todos}
    assert len(trip.documents) == 1 and trip.documents[0].incident_id is None


def test_假實作都符合行程版的選配協定() -> None:
    recognizer, packager = FakeDocumentRecognizer(), FakeClaimPackager()
    assert isinstance(recognizer, TripDocumentRecognizer)
    assert isinstance(recognizer, TripDocumentRechecker)
    assert isinstance(recognizer, TripDocumentDiscarder)
    assert isinstance(recognizer, TripDocumentRenamer)
    assert isinstance(packager, TripClaimPackager)


async def recognize(trip: TripContext, name: str, target: uuid.UUID | None = None):
    return await FakeDocumentRecognizer().recognize_trip(
        trip,
        UploadedFile(
            file_name=name,
            content_type="application/pdf",
            content=b"x",
            target_todo_id=target,
        ),
        USER,
        _NoGoogle(),
    )


async def test_共同文件上傳後檔名用_共同文件_待辦名稱_序號() -> None:
    trip, _, _, _, shared = make_trip()

    result = await recognize(trip, "診斷.pdf", target=shared.id)

    assert result.status == "recognized" and result.matched_todo_id == shared.id
    assert result.stored_name == "共同文件_理賠申請書_1.pdf"


async def test_事件的文件用事故名稱當前綴() -> None:
    trip, a, _, _, _ = make_trip()

    result = await recognize(trip, "證明.pdf", target=a.id)

    assert result.stored_name == "班機延誤_班機延誤證明_1.pdf"


async def test_歧義時回需要確認並列出各事件的候選待辦() -> None:
    trip, a, b, gone, _ = make_trip()

    result = await recognize(trip.for_agents_6_7(), "歧義.pdf")

    assert result.status == "needs_review" and result.matched_todo_id is None
    assert set(result.candidate_todo_ids) == {a.id, b.id}  # 不符保障的事件不列


async def test_行程版的打包涵蓋全部符合保障的事件() -> None:
    trip, a, b, gone, shared = make_trip()

    package = await FakeClaimPackager().build_trip(trip)

    assert set(package.missing_todo_ids) == {a.id, b.id, shared.id}
    assert "【班機延誤】" in package.body and "【行李遺失】" in package.body
    assert "不符保障" not in package.body


async def test_共同文件與事件的文件二選一(session: AsyncSession) -> None:
    user = User(email="trip@example.com")
    session.add(user)
    await session.flush()
    policy = Policy(
        user_id=user.id, display_name="p", plan_id="fubon_advanced", sum_insured=1
    )
    session.add(policy)
    await session.flush()
    inc = Incident(policy_id=policy.id, title="t", description="d")
    session.add(inc)
    await session.flush()

    def doc(**kw: object) -> IncidentDocument:
        return IncidentDocument(
            file_name="x.pdf",
            size_bytes=1,
            storage_path="p",
            content_type="application/pdf",
            **kw,  # pyright: ignore[reportArgumentType]
        )

    session.add_all([doc(incident_id=inc.id), doc(policy_id=policy.id)])
    await session.commit()  # 事件的文件與共同文件都可以

    for bad in (doc(), doc(incident_id=inc.id, policy_id=policy.id)):
        session.add(bad)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


async def test_seed_把_D02_D10_D11_D24_標成共同文件(session: AsyncSession) -> None:
    await load_incident_catalog(session)

    rows = (await session.exec(select(TodoTemplate))).all()
    shared = {t.document_code for t in rows if t.shared}
    # D11（存摺封面與護照影本）目前沒有任何事故類型使用，所以沒有範本可標
    assert shared == {"D02", "D10", "D24"}
    # 理賠申請書另有不屬於任何事故類型的範本，共同文件不重複
    assert [t.document_code for t in rows if t.incident_type_id is None] == ["D10"]
    assert not any(t.shared for t in rows if t.document_code not in shared)

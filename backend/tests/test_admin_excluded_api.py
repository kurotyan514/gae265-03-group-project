"""不收錄區：設成不收錄時存快照，做錯可以單條（或整個險種）收錄回來，不用整本重新上傳。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag import hybrid
from app.domain.rag.hybrid import search_rules
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from app.models import ExcludedRule, Insurance, InsuranceRule, RuleEmbedding
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("logged_in")


def rule(code: str, no: int, title: str, content: str, **kw) -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", title, content, kw.get("section"), f"{code}.pdf", no, no,
        subsection=kw.get("subsection"),
    )  # fmt: skip


SPECS = [
    InsuranceSpec("T001", "甲險", approval_no="甲字第1號", approval_date="113.1.1")
]
RULES = [
    rule("T001", 1, "名詞定義", "本保險契約所稱被保險人"),
    rule("T001", 25, "承保範圍", "被保險人於滑雪場發生意外事故", section="第三章 傷害醫療", subsection="第二節 滑雪"),
]  # fmt: skip


@pytest.fixture(autouse=True)
async def catalog_loaded(session: AsyncSession) -> None:
    hybrid._index_cache = None
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )


async def archived(session: AsyncSession) -> list[ExcludedRule]:
    return list((await session.exec(select(ExcludedRule))).all())


async def rule_row(session: AsyncSession, no: int) -> InsuranceRule | None:
    return (
        await session.exec(
            select(InsuranceRule)
            .join(Insurance)
            .where(Insurance.code == "T001", InsuranceRule.article_no == no)
        )
    ).first()


async def vector_count(session: AsyncSession, rule_id: uuid.UUID) -> int:
    return len(
        (
            await session.exec(
                select(RuleEmbedding).where(
                    RuleEmbedding.rule_id == rule_id,
                    RuleEmbedding.model == embedding_model_name(),
                )
            )
        ).all()
    )


async def test_不收錄一條時存下快照(client: AsyncClient, session: AsyncSession) -> None:
    original = await rule_row(session, 25)
    assert original is not None

    response = await client.delete(
        "/admin/rules/T001/25", params={"reason": "不是條款"}
    )

    assert response.status_code == 200, response.text
    assert "可以收錄回來" in response.json()["message"]
    snap = (await archived(session))[0]
    assert (snap.insurance_code, snap.insurance_name, snap.article_no) == (
        "T001",
        "甲險",
        25,
    )
    assert (snap.title, snap.content, snap.section, snap.subsection) == (
        "承保範圍", "被保險人於滑雪場發生意外事故", "第三章 傷害醫療", "第二節 滑雪",
    )  # fmt: skip
    assert (snap.reason, snap.whole_insurance, snap.rule_id) == (
        "不是條款",
        False,
        original.id,
    )
    assert (snap.approval_no, snap.approval_date) == ("甲字第1號", "113.1.1")


async def test_清單帶出是否已經有同一條與險種還在不在(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.delete("/admin/rules/T001/25")

    listed = (await client.get("/admin/excluded")).json()

    assert listed["total"] == 1
    item = listed["items"][0]
    assert (item["article_no"], item["in_catalog"], item["insurance_exists"]) == (
        25,
        False,
        True,
    )
    assert item["subsection"] == "第二節 滑雪"
    # 重新上傳又讀進來了：清單要看得出來
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )
    assert (await client.get("/admin/excluded")).json()["items"][0][
        "in_catalog"
    ] is True


async def test_清單可以依險種與文字篩選(client: AsyncClient) -> None:
    await client.delete("/admin/rules/T001/1")
    await client.delete("/admin/rules/T001/25")

    by_text = (await client.get("/admin/excluded", params={"q": "滑雪"})).json()
    by_code = (
        await client.get("/admin/excluded", params={"insurance_code": "T001"})
    ).json()
    other = (
        await client.get("/admin/excluded", params={"insurance_code": "NOPE"})
    ).json()

    assert [i["article_no"] for i in by_text["items"]] == [25]
    assert by_code["total"] == 2
    assert other["total"] == 0


async def test_收錄回來_條文與向量都回來_沿用原本的_id(
    client: AsyncClient, session: AsyncSession
) -> None:
    original = await rule_row(session, 25)
    assert original is not None
    original_id = original.id
    await client.delete("/admin/rules/T001/25")
    assert await rule_row(session, 25) is None
    snap = (await archived(session))[0]

    response = await client.post(
        "/admin/excluded/restore", json={"ids": [str(snap.id)]}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restored"] == [{"insurance_code": "T001", "article_no": 25}]
    assert body["skipped"] == [] and body["insurances_created"] == []
    back = await rule_row(session, 25)
    assert back is not None and back.id == original_id
    assert (back.title, back.content, back.section, back.subsection) == (
        "承保範圍", "被保險人於滑雪場發生意外事故", "第三章 傷害醫療", "第二節 滑雪",
    )  # fmt: skip
    assert await vector_count(session, back.id) == 1  # 只重算這一條
    assert await archived(session) == []  # 快照用掉了
    hits = await search_rules(session, "滑雪場", mode="keyword", k=3)
    assert [h.article_no for h in hits][:1] == [25]  # 檢索馬上找得到


async def test_整個險種不收錄後可以整個收錄回來(
    client: AsyncClient, session: AsyncSession
) -> None:
    insurance = (
        await session.exec(select(Insurance).where(Insurance.code == "T001"))
    ).one()
    insurance_id = insurance.id
    insurance.policy_codes = {"第三章 傷害醫療": "T068"}
    session.add(insurance)
    await session.commit()
    await client.delete("/admin/insurances/T001")
    snaps = await archived(session)
    assert len(snaps) == 2 and all(s.whole_insurance for s in snaps)

    response = await client.post(
        "/admin/excluded/restore", json={"ids": [str(s.id) for s in snaps]}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["restored"]) == 2 and body["insurances_created"] == ["T001"]
    back = (await session.exec(select(Insurance).where(Insurance.code == "T001"))).one()
    assert (back.id, back.name, back.approval_no) == (insurance_id, "甲險", "甲字第1號")
    assert back.policy_codes == {"第三章 傷害醫療": "T068"}
    assert (await rule_row(session, 1)) is not None and (
        await rule_row(session, 25)
    ) is not None


async def test_條文表已經有同一條就略過並說明(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.delete("/admin/rules/T001/25")
    await import_catalog(  # 重新上傳合訂本又讀進來了
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )
    snap = (await archived(session))[0]

    body = (
        await client.post("/admin/excluded/restore", json={"ids": [str(snap.id)]})
    ).json()

    assert body["restored"] == []
    assert "已經有這一條" in body["skipped"][0]["reason"]
    assert len(await archived(session)) == 1  # 快照還在，可以自己刪


async def test_險種名稱被別的險種佔用就略過(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.delete("/admin/insurances/T001")
    await import_catalog(
        session,
        [InsuranceSpec("T009", "甲險")],  # 換了代碼、同名
        [rule("T009", 1, "名詞定義", "內文")],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )
    snaps = await archived(session)

    body = (
        await client.post(
            "/admin/excluded/restore", json={"ids": [str(s.id) for s in snaps]}
        )
    ).json()

    assert body["restored"] == [] and len(body["skipped"]) == 2
    assert "T009" in body["skipped"][0]["reason"]


async def test_向量服務失敗時什麼都不動(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await client.delete("/admin/rules/T001/25")
    snap = (await archived(session))[0]

    class Broken:
        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("provider down")

    monkeypatch.setattr(
        "app.api.routes.admin_excluded.get_embeddings", lambda: Broken()
    )

    response = await client.post(
        "/admin/excluded/restore", json={"ids": [str(snap.id)]}
    )

    assert response.status_code == 502
    assert "沒有任何條文被收錄回來" in response.json()["detail"]
    assert await rule_row(session, 25) is None
    assert len(await archived(session)) == 1


async def test_同一條有多份快照只收錄最新的(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.delete("/admin/rules/T001/25")
    newest = (await archived(session))[0]
    older = ExcludedRule(
        insurance_code="T001", insurance_name="甲險", article_no=25, chapter="條文25",
        title="舊標題", content="舊內文", source_file="T001.pdf", page_start=25, page_end=25,
    )  # fmt: skip
    session.add(older)
    await session.commit()
    older.created_at = datetime.now(UTC) - timedelta(days=1)
    session.add(older)
    await session.commit()

    body = (
        await client.post(
            "/admin/excluded/restore", json={"ids": [str(newest.id), str(older.id)]}
        )
    ).json()

    assert len(body["restored"]) == 1 and len(body["skipped"]) == 1
    back = await rule_row(session, 25)
    assert back is not None and back.title == "承保範圍"  # 最新的那份


async def test_找不到的快照回_404(client: AsyncClient) -> None:
    response = await client.post(
        "/admin/excluded/restore", json={"ids": [str(uuid.uuid4())]}
    )

    assert response.status_code == 404


async def test_從不收錄區永久刪除一份快照(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.delete("/admin/rules/T001/25")
    snap = (await archived(session))[0]

    assert (await client.delete(f"/admin/excluded/{snap.id}")).status_code == 200

    assert await archived(session) == []
    assert (await client.delete(f"/admin/excluded/{snap.id}")).status_code == 404
    assert (
        await client.post("/admin/excluded/restore", json={"ids": [str(snap.id)]})
    ).status_code == 404


async def test_險種還在使用中不給刪_也不會留下快照(
    client: AsyncClient, session: AsyncSession
) -> None:
    await import_catalog(
        session,
        [InsuranceSpec("FUBON01", "富邦旅行平安")],
        [rule("FUBON01", 1, "名詞定義", "內文")],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )

    assert (await client.delete("/admin/insurances/FUBON01")).status_code == 409

    assert await archived(session) == []

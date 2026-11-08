"""後台條文維護：GET /admin/rules 列出條文，PATCH /admin/rules/{險種}/{條號} 改標題與內文並重新算這一條的向量。整組要登入。"""

import pytest
from app.api.main import build_api_router
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag.hybrid import search_rules
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from app.models import Insurance, InsuranceRule, RuleEmbedding
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.middleware.sessions import SessionMiddleware


def rule(code: str, no: int, title: str, content: str) -> ParsedRule:
    return ParsedRule(
        code, no, f"條文{no}", title, content, None, f"{code}.pdf", no, no
    )


SPECS = [InsuranceSpec("T001", "甲險")]
RULES = [
    rule("T001", 1, "名詞定義", "本保險契約所稱被保險人"),
    rule("T001", 25, "承保範圍", "被保險人於滑雪場發生意外事故"),
]


@pytest.fixture(autouse=True)
async def catalog_loaded(session: AsyncSession) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )
    # 另一個 model 留下的舊向量：內容改了就對不上，要一併刪掉
    await import_catalog(
        session,
        SPECS,
        RULES[1:],
        embeddings=get_embeddings(),
        model="other-model",
        prune=False,  # 預設會把不在清單裡的第 1 條刪掉
    )


async def stored(session: AsyncSession, article_no: int) -> InsuranceRule:
    row = (
        await session.exec(
            select(InsuranceRule)
            .join(Insurance)
            .where(Insurance.code == "T001", InsuranceRule.article_no == article_no)
        )
    ).one()
    await session.refresh(row)
    return row


async def vectors(session: AsyncSession, rule_id) -> dict[str, list[float]]:
    rows = (
        await session.exec(
            select(RuleEmbedding).where(col(RuleEmbedding.rule_id) == rule_id)
        )
    ).all()
    return {r.model: list(r.embedding) for r in rows}


@pytest.mark.usefixtures("logged_in")
async def test_改標題與內文_重新算向量_只留目前的_model(
    client: AsyncClient, session: AsyncSession
) -> None:
    before = await stored(session, 25)
    old_vectors = await vectors(session, before.id)
    assert set(old_vectors) == {embedding_model_name(), "other-model"}

    response = await client.patch(
        "/admin/rules/T001/25",
        json={
            "title": "  滑雪承保範圍  ",
            "content": "被保險人於雪地從事滑雪發生意外",
            "reason": "勘誤",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "滑雪承保範圍"  # 去掉前後空白
    assert body["content"] == "被保險人於雪地從事滑雪發生意外"
    assert body["embedding_models"] == [embedding_model_name()]
    after = await stored(session, 25)
    assert (after.title, after.content) == (
        "滑雪承保範圍",
        "被保險人於雪地從事滑雪發生意外",
    )
    new_vectors = await vectors(session, after.id)
    assert set(new_vectors) == {embedding_model_name()}  # 別的 model 的舊向量刪了
    assert new_vectors[embedding_model_name()] != old_vectors[embedding_model_name()]


@pytest.mark.usefixtures("logged_in")
async def test_檢索馬上看得到新內容(client: AsyncClient, session: AsyncSession) -> None:
    await client.patch(
        "/admin/rules/T001/25", json={"content": "被保險人於潛水時發生意外事故"}
    )

    hits = await search_rules(session, "潛水", mode="keyword", k=3)
    assert [(h.insurance_code, h.article_no) for h in hits][:1] == [("T001", 25)]
    assert await search_rules(session, "滑雪場", mode="keyword", k=3) == []


@pytest.mark.usefixtures("logged_in")
async def test_只改標題或只改內文都可以(
    client: AsyncClient, session: AsyncSession
) -> None:
    only_title = await client.patch("/admin/rules/T001/1", json={"title": "用詞定義"})
    assert only_title.status_code == 200, only_title.text
    assert (await stored(session, 1)).content == "本保險契約所稱被保險人"

    only_content = await client.patch(
        "/admin/rules/T001/1", json={"content": "本保險契約所稱要保人"}
    )
    assert only_content.status_code == 200, only_content.text
    assert (await stored(session, 1)).title == "用詞定義"


@pytest.mark.usefixtures("logged_in")
@pytest.mark.parametrize(
    ("path", "body", "code"),
    [
        ("/admin/rules/T001/25", {"title": "   "}, 422),
        ("/admin/rules/T001/25", {"content": ""}, 422),
        ("/admin/rules/T001/25", {}, 409),
        ("/admin/rules/T001/25", {"title": "承保範圍"}, 409),  # 跟原本一樣
        ("/admin/rules/T001/999", {"title": "x"}, 404),
        ("/admin/rules/NOPE/1", {"title": "x"}, 404),
    ],
)
async def test_不合理的修改被擋下_條文不變(
    path: str, body: dict, code: int, client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.patch(path, json=body)

    assert response.status_code == code, response.text
    unchanged = await stored(session, 25)
    assert (unchanged.title, unchanged.content) == (
        "承保範圍",
        "被保險人於滑雪場發生意外事故",
    )


@pytest.mark.usefixtures("logged_in")
async def test_向量服務失敗時標題內文都不動(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            raise RuntimeError("provider down")

    monkeypatch.setattr("app.api.routes.admin_rules.get_embeddings", lambda: Broken())
    before = await stored(session, 25)
    old_vectors = await vectors(session, before.id)

    response = await client.patch("/admin/rules/T001/25", json={"title": "新標題"})

    assert response.status_code == 502
    assert "沒有修改" in response.json()["detail"]
    after = await stored(session, 25)
    assert after.title == "承保範圍"
    assert await vectors(session, after.id) == old_vectors  # 舊向量還在


async def test_沒登入不能改(client: AsyncClient, session: AsyncSession) -> None:
    response = await client.patch("/admin/rules/T001/25", json={"title": "新標題"})

    assert response.status_code == 401
    assert (await stored(session, 25)).title == "承保範圍"


async def test_清單要登入才看得到(client: AsyncClient) -> None:
    response = await client.get("/admin/rules")

    assert response.status_code == 401


@pytest.mark.usefixtures("logged_in")
async def test_清單帶向量狀態_可以依險種與文字篩選(client: AsyncClient) -> None:
    everything = (await client.get("/admin/rules")).json()
    assert everything["total"] == 2
    assert all(r["embedding_models"] for r in everything["items"])  # 都有向量

    found = (
        await client.get("/admin/rules", params={"q": "滑雪", "insurance_code": "T001"})
    ).json()
    assert [(r["insurance_code"], r["article_no"]) for r in found["items"]] == [
        ("T001", 25)
    ]


@pytest.mark.parametrize("environment", ["development", "production"])
async def test_所有環境都註冊條文維護端點_且都要登入(environment: str) -> None:
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.include_router(build_api_router(environment))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get("/admin/rules")
        edited = await client.patch("/admin/rules/T001/25", json={"title": "x"})

    assert listed.status_code == 401  # 不是 404：路由存在，只是要登入
    assert edited.status_code == 401


@pytest.mark.usefixtures("logged_in")
async def test_節會存進資料庫_也出現在清單與檢索結果(
    client: AsyncClient, session: AsyncSession
) -> None:
    await import_catalog(
        session,
        [InsuranceSpec("T003", "丙險")],
        [
            ParsedRule(
                "T003", 29, "條文二十九", "理賠文件", "應檢具機票及登機證",
                "第三章 個人海外旅行不便保險", "T003.pdf", 3, 3,
                subsection="第二節 班機延誤保險(定額給付-累進式)",
            )
        ],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )  # fmt: skip

    listed = (
        await client.get("/admin/rules", params={"insurance_code": "T003"})
    ).json()
    assert listed["items"][0]["subsection"] == "第二節 班機延誤保險(定額給付-累進式)"
    assert listed["items"][0]["section"] == "第三章 個人海外旅行不便保險"  # 章不變

    hits = await search_rules(session, "機票及登機證", mode="keyword", k=3)
    assert hits[0].subsection == "第二節 班機延誤保險(定額給付-累進式)"
    # 節進了檢索用的文字：只搜節名也找得到這一條
    by_subsection = await search_rules(session, "班機延誤保險", mode="keyword", k=3)
    assert [h.article_no for h in by_subsection][:1] == [29]


@pytest.mark.usefixtures("logged_in")
async def test_沒有節的條文節是空的(client: AsyncClient) -> None:
    listed = (
        await client.get("/admin/rules", params={"insurance_code": "T001"})
    ).json()
    assert {r["subsection"] for r in listed["items"]} == {None}

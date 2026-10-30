"""seed 匯出入：把險種、條文、向量存成 JSON.gz，其他人 make seed 就有同一份資料（保留 UUID）。"""

import gzip
import json
import uuid
from pathlib import Path

import pytest
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag.hybrid import search_rules
from app.ingest.catalog import InsuranceSpec, ParsedRule, embedding_text, import_catalog
from app.models import Insurance, InsuranceRule, RuleEmbedding
from app.seed import (
    SEED_PATH,
    SEED_VERSION,
    export_seed,
    load_seed,
    read_seed,
    write_seed,
)
from sqlalchemy import delete, func
from sqlalchemy import select as sa_select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.domain.golden_support import golden_rules_with_errata

SPECS = [
    InsuranceSpec("T001", "甲險", "富保業字第1130004861號函備查", "113.11.29"),
    InsuranceSpec("T002", "乙險"),  # 沒有文號
]
RULES = [
    ParsedRule("T001", 1, "條文一", "名詞定義", "本保險契約所稱被保險人", None, "T001.pdf", 1, 1),
    ParsedRule("T001", 25, "條文二十五", "承保範圍", "被保險人於滑雪場發生意外事故", "第三章 傷害醫療", "T001.pdf", 3, 4),
    ParsedRule("T002", 1, "條文一", "班機延誤", "搭乘之班機延誤超過六小時", None, "T002.pdf", 1, 1),
]  # fmt: skip


async def count(session: AsyncSession, table) -> int:
    return await session.scalar(sa_select(func.count()).select_from(table)) or 0


async def wipe(session: AsyncSession) -> None:
    await session.exec(delete(Insurance))  # 條文與向量由 ON DELETE CASCADE 一起刪
    await session.commit()


@pytest.fixture
async def imported(session: AsyncSession) -> None:
    await import_catalog(
        session, SPECS, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )


@pytest.mark.usefixtures("imported")
async def test_export_has_rows_ids_and_vectors_of_one_model(
    session: AsyncSession,
) -> None:
    data = await export_seed(session, embedding_model_name())
    assert data["version"] == SEED_VERSION
    assert (data["embedding_model"], data["dimensions"]) == (
        embedding_model_name(),
        settings.EMBEDDING_DIMENSIONS,
    )
    assert [i["code"] for i in data["insurances"]] == ["T001", "T002"]
    assert [(r["insurance_code"], r["article_no"]) for r in data["rules"]] == [
        ("T001", 1),
        ("T001", 25),
        ("T002", 1),
    ]
    assert all(uuid.UUID(r["id"]) for r in data["rules"])
    assert len(data["embeddings"]) == 3
    assert {len(e["embedding"]) for e in data["embeddings"]} == {
        settings.EMBEDDING_DIMENSIONS
    }
    assert {e["rule_id"] for e in data["embeddings"]} == {
        r["id"] for r in data["rules"]
    }


@pytest.mark.usefixtures("imported")
async def test_export_fails_when_the_model_has_no_vectors(
    session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="沒有.*向量"):
        await export_seed(session, "no-such-model")


@pytest.mark.usefixtures("imported")
async def test_roundtrip_through_a_file_restores_same_ids_content_and_search(
    session: AsyncSession, tmp_path: Path
) -> None:
    before = await export_seed(session, embedding_model_name())
    path = tmp_path / "seed.json.gz"
    write_seed(before, path)

    await wipe(session)
    assert await count(session, InsuranceRule) == 0
    result = await load_seed(session, read_seed(path))

    assert (result.insurances, result.rules, result.embeddings) == (2, 3, 3)
    after = await export_seed(session, embedding_model_name())
    assert after["rules"] == before["rules"]  # id 與內容都一樣
    assert [i["id"] for i in after["insurances"]] == [
        i["id"] for i in before["insurances"]
    ]
    assert after["insurances"] == before["insurances"]  # 含文號
    assert before["insurances"][0]["approval_no"] == "富保業字第1130004861號函備查"
    assert before["insurances"][1]["approval_no"] is None
    for got, want in zip(after["embeddings"], before["embeddings"], strict=True):
        assert got["rule_id"] == want["rule_id"]
        assert got["embedding"] == pytest.approx(want["embedding"], abs=1e-7)
    hits = await search_rules(session, "滑雪場", mode="keyword")
    assert [(h.insurance_code, h.article_no) for h in hits] == [("T001", 25)]
    same_text = embedding_text(
        "乙險", RULES[2]
    )  # fake embedding 沒有語意，用和條文完全相同的文字查
    top = (await search_rules(session, same_text, mode="vector", k=1))[0]
    assert (top.insurance_code, top.article_no) == ("T002", 1)


@pytest.mark.usefixtures("imported")
async def test_loading_twice_is_idempotent(session: AsyncSession) -> None:
    data = await export_seed(session, embedding_model_name())
    await load_seed(session, data)
    await load_seed(session, data)
    assert [
        await count(session, t) for t in (Insurance, InsuranceRule, RuleEmbedding)
    ] == [2, 3, 3]


@pytest.mark.usefixtures("imported")
async def test_written_file_is_gzip_json_and_byte_for_byte_reproducible(
    session: AsyncSession, tmp_path: Path
) -> None:
    data = await export_seed(session, embedding_model_name())
    a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    write_seed(data, a)
    write_seed(data, b)
    assert (
        a.read_bytes() == b.read_bytes()
    )  # gzip 檔頭不含時間，git diff 才不會每次都變
    assert json.loads(gzip.decompress(a.read_bytes()))["version"] == SEED_VERSION


@pytest.mark.usefixtures("imported")
async def test_dimension_mismatch_is_rejected_with_a_clear_message(
    session: AsyncSession,
) -> None:
    data = await export_seed(session, embedding_model_name())
    data["dimensions"] = 3072
    with pytest.raises(ValueError, match="3072.*1024"):
        await load_seed(session, data)


@pytest.mark.usefixtures("imported")
async def test_unknown_version_is_rejected(session: AsyncSession) -> None:
    data = await export_seed(session, embedding_model_name())
    data["version"] = 999
    with pytest.raises(ValueError, match="版本"):
        await load_seed(session, data)


@pytest.mark.usefixtures("imported")
async def test_conflicting_ids_in_the_database_are_rejected(
    session: AsyncSession,
) -> None:
    data = await export_seed(session, embedding_model_name())
    data["insurances"][0]["id"] = str(uuid.uuid4())  # 同一個代碼、不同 id
    with pytest.raises(ValueError, match="T001.*db-reset"):
        await load_seed(session, data)


@pytest.mark.usefixtures("imported")
async def test_vectors_can_be_relabelled_to_the_local_model_name(
    session: AsyncSession,
) -> None:
    data = await export_seed(session, embedding_model_name())
    await wipe(session)
    await load_seed(session, data, as_model="my-local-deployment")
    models = set((await session.exec(select(RuleEmbedding.model))).all())
    assert models == {"my-local-deployment"}


async def test_the_committed_seed_file_matches_the_parsed_clauses(
    session: AsyncSession,
) -> None:
    """backend/data/seed/catalog.json.gz 的條文必須和 16 份條款 PDF 的解析結果一致（對照資料）。"""
    data = read_seed(SEED_PATH)
    golden_rules = golden_rules_with_errata()  # seed 是匯入後的結果，已套勘誤
    assert (len(data["insurances"]), len(data["rules"]), len(data["embeddings"])) == (
        16,
        281,
        281,
    )
    assert [
        (r["insurance_code"], r["article_no"], r["title"], r["content"])
        for r in data["rules"]
    ] == [
        (r["insurance_id"], r["article_no"], r["title"], r["content"])
        for r in golden_rules
    ]
    result = await load_seed(session, data)
    assert (result.insurances, result.rules, result.embeddings) == (16, 281, 281)

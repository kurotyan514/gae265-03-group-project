"""保單上傳 API（ADR-0013）：驗檔、抽文字，用承保內容表的險種代碼對照方案；比對不到就拒絕，且不留下資料。"""

import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import import_catalog
from app.main import app
from app.models import (
    Conversation,
    ConversationInsurance,
    Insurance,
    Policy,
    PolicyAddon,
    User,
)
from app.policy.table import load_code_map
from app.seed import load_policy_codes
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.policy.support import (
    ADVANCED_CODES,
    BASIC_CODES,
    FAKE_NAME,
    PII,
    SUMMARY_LAYOUT,
    clause_pages,
    fubon_policy_text,
    make_pdf,
    make_scanned_pdf,
)


def upload(data: bytes, content_type: str = "application/pdf") -> dict:
    return {"files": {"file": ("policy.pdf", data, content_type)}}


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
async def catalog_loaded(session: AsyncSession, catalog) -> None:
    specs, rules = catalog
    await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=embedding_model_name()
    )
    await load_policy_codes(session)  # 比對讀資料庫的保單代碼（make seed 會做這一步）


TAIPEI = ZoneInfo("Asia/Taipei")
UPLOAD_ONLY_FIELDS = {"product_name", "riders", "auto_filled"}  # 只出現在上傳那次的回應


def policy_pdf(codes: list[str] = ADVANCED_CODES, **layout: Any) -> bytes:
    """承保內容表印了這些險種代碼；個資放在首頁，後面附條款。layout 調整首頁其他欄位的版面。"""
    text = fubon_policy_text(codes, **layout)
    lines = (f"被保險人 : {FAKE_NAME}\n" + text).split("\n")
    return make_pdf(["\n".join(lines[i : i + 40]) for i in range(0, len(lines), 40)])


async def count(session: AsyncSession, model: type) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_advanced_policy_is_matched_by_codes_and_keeps_amount_and_period(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 201, response.text
    body = response.json()
    assert (
        body["plan_id"] == "fubon_advanced"
    )  # 基礎型與進階型險種代碼一樣，靠表上的代碼分
    assert body["plan_name"] == "富邦國外旅平險-進階型"
    assert body["display_name"].startswith(body["plan_name"])  # 不用原檔名
    assert [i["code"] for i in body["insurances"]] == [
        f"FUBON0{n}" for n in range(1, 7)
    ]
    assert body["addons"] == []
    assert (body["sum_insured"], body["start_date"], body["end_date"]) == (
        6_000_000,
        "2026-05-28",
        "2026-06-05",
    )
    assert await count(session, PolicyAddon) == 0

    stored = {k: v for k, v in body.items() if k not in UPLOAD_ONLY_FIELDS}
    assert (await client.get(f"/policies/{body['id']}")).json() == stored
    assert [p["id"] for p in (await client.get("/policies")).json()] == [body["id"]]


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_basic_policy_is_matched_to_the_basic_plan(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(policy_pdf(BASIC_CODES)))
    assert response.status_code == 201, response.text
    assert response.json()["plan_id"] == "fubon_basic"


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_official_c_plan_policy_matches_the_upload_only_plan(
    client: AsyncClient, session: AsyncSession
) -> None:
    """進階型的 19 個代碼加上 TA35（特定票券取消）是官網 C 方案（加購）：整組都在方案裡，沒有加購。"""
    response = await client.post(
        "/policies", **upload(policy_pdf([*ADVANCED_CODES, "TA35"]))
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == "fubon_official_c_addon"
    assert body["plan_name"] == "富邦國外旅平險-官網C方案（加購）"
    assert body["addons"] == []
    assert await count(session, PolicyAddon) == 0


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_advanced_plan_codes_alone_still_match_the_advanced_plan(
    client: AsyncClient,
) -> None:
    response = await client.post("/policies", **upload(policy_pdf(ADVANCED_CODES)))
    assert response.status_code == 201, response.text
    assert response.json()["plan_id"] == "fubon_advanced"


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_extra_coverage_is_recorded_as_an_addon_with_its_chapter(
    client: AsyncClient, session: AsyncSession
) -> None:
    """基礎型多印了居家火災臨時住宿（TA30）：方案不變，多出的章是加購。"""
    response = await client.post(
        "/policies", **upload(policy_pdf([*BASIC_CODES, "TA30"]))
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == "fubon_basic"
    assert body["addons"] == [
        {
            "code": "FUBON04",
            "name": "富邦產物安心個人旅行綜合保險-甲型",
            "section": "第四章 居家火災臨時住宿補償保險",
        }
    ]
    assert await count(session, PolicyAddon) == 1


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_codes_filled_in_the_backoffice_take_effect_without_reseed(
    client: AsyncClient, session: AsyncSession
) -> None:
    """比對讀資料庫的險種代碼：後台多填的一個章代碼（JSON 沒有）立刻認得，成為加購。"""
    by_insurance: dict[str, dict[str, str]] = {}
    for code, target in load_code_map().items():
        by_insurance.setdefault(target.insurance, {})[target.section or ""] = code
    by_insurance["FUBON04"]["第四章 居家火災臨時住宿補償保險"] = "T972"  # 取代 TA30
    for ins in (await session.exec(select(Insurance))).all():
        if ins.code in by_insurance:
            ins.policy_codes = by_insurance[ins.code]
            session.add(ins)
    await session.commit()

    response = await client.post(
        "/policies", **upload(policy_pdf([*BASIC_CODES, "T972"]))
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == "fubon_basic"
    assert [(a["code"], a["section"]) for a in body["addons"]] == [
        ("FUBON04", "第四章 居家火災臨時住宿補償保險")
    ]


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_policy_missing_one_of_the_plans_coverages_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(policy_pdf(BASIC_CODES[:-1])))
    assert response.status_code == 422
    assert "條款庫裡沒有這份保單的商品方案" in response.json()["detail"]
    assert await count(session, Policy) == 0
    assert await count(session, PolicyAddon) == 0


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_without_a_known_code_table_it_falls_back_to_product_names(
    client: AsyncClient,
) -> None:
    """其他公司的保單沒有代碼對照時，用商品全名比對；全名沒寫齊就比對不到。"""
    response = await client.post(
        "/policies", **upload(make_pdf([SUMMARY_LAYOUT, *clause_pages()]))
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("user")
async def test_empty_catalog_rejects_the_upload(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(make_pdf([SUMMARY_LAYOUT])))
    assert response.status_code == 422
    assert await count(session, Policy) == 0


@pytest.mark.usefixtures("catalog_loaded")
async def test_nothing_from_the_pdf_is_stored_or_logged(
    client: AsyncClient,
    session: AsyncSession,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 201, response.text

    policy = (await session.exec(select(Policy))).one()
    assert policy.user_id == user.id
    stored = f"{policy.display_name} {policy.plan_id} {response.text}"
    assert [p for p in PII if p in stored] == []
    assert FAKE_NAME not in stored
    assert [p for p in PII if p in caplog.text] == []
    assert policy.sum_insured == 6_000_000  # 保額照存，個資不存
    assert policy.start_date == date(2026, 5, 28)


@pytest.mark.usefixtures("user")
async def test_scanned_pdf_is_rejected_with_a_clear_error(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(make_scanned_pdf()))
    assert response.status_code == 422
    assert "沒有文字層" in response.json()["detail"]


@pytest.mark.usefixtures("user")
async def test_non_pdf_is_rejected(client: AsyncClient) -> None:
    wrong_type = await client.post("/policies", **upload(policy_pdf(), "text/plain"))
    assert wrong_type.status_code == 415
    wrong_header = await client.post("/policies", **upload(b"hello"))
    assert wrong_header.status_code == 415


@pytest.mark.usefixtures("user")
async def test_file_over_the_size_limit_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "POLICY_MAX_UPLOAD_MB", 1)
    big = b"%PDF-" + b"0" * (1024 * 1024)
    response = await client.post("/policies", **upload(big))
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]


async def test_upload_requires_login(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 401


@pytest.mark.usefixtures("user")
async def test_other_users_policy_is_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = User(email="b@example.com")
    session.add(other)
    await session.commit()
    policy = Policy(user_id=other.id, display_name="別人的", plan_id="fubon_advanced")
    session.add(policy)
    await session.commit()
    assert (await client.get(f"/policies/{policy.id}")).status_code == 404
    assert (await client.get(f"/policies/{uuid.uuid4()}")).status_code == 404
    assert (
        await client.post(f"/policies/{policy.id}/conversations")
    ).status_code == 404
    assert (await client.get("/policies")).json() == []


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_asking_about_a_policy_covers_the_plan_and_its_addons(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy_id = (
        await client.post("/policies", **upload(policy_pdf([*BASIC_CODES, "TA30"])))
    ).json()["id"]
    response = await client.post(f"/policies/{policy_id}/conversations")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == "fubon_basic"
    # 加購的 FUBON04 已經在方案裡，不重複
    assert body["insurance_codes"] == [f"FUBON0{n}" for n in range(1, 7)]

    conversation = await session.get(Conversation, uuid.UUID(body["id"]))
    assert conversation is not None
    assert conversation.user_id == user.id
    assert str(conversation.policy_id) == policy_id
    assert await count(session, ConversationInsurance) == 6


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_upload_returns_everything_read_from_the_policy(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["company"] == "富邦產物"
    assert body["destination"] == "日本"  # 四行日本的地區只留一次
    assert datetime.fromisoformat(body["start_at"]) == datetime(
        2026, 5, 28, 9, 0, tzinfo=TAIPEI
    )
    assert datetime.fromisoformat(body["end_at"]) == datetime(
        2026, 6, 5, 9, 0, tzinfo=TAIPEI
    )
    assert (body["start_date"], body["end_date"]) == ("2026-05-28", "2026-06-05")
    assert body["product_name"] == "【官網】國外旅平險_C方案_加購_115.04版(含法傳)"
    assert body["riders"] == [
        "傷害保險恐怖主義行為保險限額給付附加條款",
        "個人海外旅行不便保險班機延誤理賠文件簡化附加條款",
    ]
    assert body["auto_filled"] == [
        "company",
        "plan",
        "sum_insured",
        "destination",
        "period",
    ]

    # 查詢回應有公司、目的地與完整時間，但不含只在上傳回應出現的欄位
    stored = (await client.get(f"/policies/{body['id']}")).json()
    assert stored["company"] == "富邦產物"
    assert stored["destination"] == "日本"
    assert stored["start_at"] == body["start_at"]
    assert UPLOAD_ONLY_FIELDS.isdisjoint(stored)
    policy = await session.get(Policy, uuid.UUID(body["id"]))
    assert policy is not None
    assert policy.destination == "日本"
    assert policy.start_at is not None and policy.end_at is not None


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_several_countries_are_joined_without_repeats(
    client: AsyncClient,
) -> None:
    countries = ["日本(本州)", "韓國(首爾)", "日本(北海道)"]
    response = await client.post("/policies", **upload(policy_pdf(countries=countries)))
    assert response.status_code == 201, response.text
    assert response.json()["destination"] == "日本、韓國"


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_policy_without_countries_is_still_created(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(policy_pdf(countries=[])))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["destination"] is None
    assert "destination" not in body["auto_filled"]
    assert await count(session, Policy) == 1


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_period_with_spaces_between_characters_is_read(
    client: AsyncClient,
) -> None:
    # 字間有空白，而且太長會折行（折在「起」後面）
    spaced = "自 民 國 1 1 5年 0 5月 2 8日 9時 0分 起\n至 民 國 1 1 5年 0 6月 0 5日 9時 0分 止"
    response = await client.post("/policies", **upload(policy_pdf(period=spaced)))
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["start_date"], body["end_date"]) == ("2026-05-28", "2026-06-05")
    assert datetime.fromisoformat(body["end_at"]) == datetime(
        2026, 6, 5, 9, 0, tzinfo=TAIPEI
    )


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_period_without_times_keeps_dates_only(client: AsyncClient) -> None:
    response = await client.post(
        "/policies",
        **upload(policy_pdf(period="自民國115年05月28日起至民國115年06月05日止")),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["start_date"], body["end_date"]) == ("2026-05-28", "2026-06-05")
    assert body["start_at"] is None and body["end_at"] is None
    assert "period" in body["auto_filled"]


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_unreadable_period_is_left_empty_not_rejected(
    client: AsyncClient,
) -> None:
    backwards = "自民國115年06月05日9時0分起至民國115年05月28日9時0分止"
    response = await client.post("/policies", **upload(policy_pdf(period=backwards)))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["start_date"] is None and body["start_at"] is None
    assert "period" not in body["auto_filled"]


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_end_time_before_start_time_on_the_same_day_keeps_dates_only(
    client: AsyncClient,
) -> None:
    same_day = "自民國115年05月28日9時0分起至民國115年05月28日8時0分止"
    response = await client.post("/policies", **upload(policy_pdf(period=same_day)))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["start_date"] == body["end_date"] == "2026-05-28"
    assert body["start_at"] is None and body["end_at"] is None


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_policy_without_product_name_or_riders_still_uploads(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/policies", **upload(policy_pdf(product_name=None, rider_lines=[]))
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["product_name"] is None
    assert body["riders"] == []


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_unrecognised_time_wording_keeps_the_dates(client: AsyncClient) -> None:
    """起日後面印「零時」等沒認得的時間寫法：日期照讀，只是沒有完整時間點。"""
    response = await client.post(
        "/policies",
        **upload(
            policy_pdf(period="自民國115年05月28日零時起至民國115年06月05日24時止")
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["start_date"], body["end_date"]) == ("2026-05-28", "2026-06-05")
    assert body["start_at"] is None and body["end_at"] is None


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_next_field_after_a_missing_riders_list_is_not_taken_as_a_rider(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/policies", **upload(policy_pdf(rider_lines=["被保險人姓名"]))
    )
    assert response.status_code == 201, response.text
    assert response.json()["riders"] == []


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_countries_label_without_a_numeral_is_read(client: AsyncClient) -> None:
    text = fubon_policy_text(ADVANCED_CODES, countries=[]).replace(
        "要保人與被保人關係 :本人", "要保人與被保人關係 :本人\n旅遊國家 :日本 (本州)"
    )
    lines = (f"被保險人 : {FAKE_NAME}\n" + text).split("\n")
    pdf = make_pdf(["\n".join(lines[i : i + 40]) for i in range(0, len(lines), 40)])
    response = await client.post("/policies", **upload(pdf))
    assert response.status_code == 201, response.text
    assert response.json()["destination"] == "日本"

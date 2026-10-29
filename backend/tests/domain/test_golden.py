"""新實作對原型（512c7b1）的對照資料逐筆比對。不一致時先查原因並回報，不改對照資料（見 golden/README.md）。"""

from dataclasses import asdict

import pytest
from app.core.config import settings
from app.domain.pricing.quote import Requirement, Traveler, quote
from app.domain.pricing.rates_schema import (
    load_rate_table,
    lookup_price,
    validate_rate_table,
)
from app.domain.pricing.tables import (
    eligible_columns,
    is_rental_car_column,
    load_main_tables,
    select_main_tables,
)
from app.domain.recommend.narrate import (
    check_numbers,
    extract_numbers,
    render_report,
    render_template,
)
from app.domain.recommend.profile import (
    TripProfile,
    TripProfilePatch,
    merge_patch,
    missing_fields,
    validate_profile,
)
from app.domain.recommend.recommend import build_recommendation
from app.domain.recommend.regions import region_of
from app.domain.recommend.requirements import requirements_for

from .golden_support import error_of, fake_warn, jsonable, load_golden

PRICING = load_golden("pricing")
PROFILE = load_golden("profile")
RECOMMEND = load_golden("recommend")
NARRATE = load_golden("narrate")

MAIN_TABLES = load_main_tables()
ALL_TABLES = {
    p.stem: load_rate_table(str(p)) for p in sorted(settings.RATES_DIR.glob("*.json"))
}


def ids(cases, key="id"):
    return [c[key] for c in cases]


# ---- pricing ----


@pytest.mark.parametrize("case", PRICING["quote"], ids=ids(PRICING["quote"]))
def test_quote_matches_golden(case):
    try:
        plans, unavailable = quote(
            case["days"],
            [Traveler(age, rents_car) for age, rents_car in case["travelers"]],
            Requirement(**case["requirement"]),
        )
        actual = {
            "plans": [asdict(p) for p in plans],
            "unavailable": [asdict(u) for u in unavailable],
        }
    except Exception as e:  # noqa: BLE001
        actual = error_of(e)
    assert jsonable(actual) == case["expected"]


def test_table_ids_match_golden():
    tables = PRICING["tables"]
    assert sorted(ALL_TABLES) == tables["all_table_ids"]
    assert sorted(select_main_tables(ALL_TABLES)) == tables["main_table_ids"]
    assert sorted(MAIN_TABLES) == tables["main_table_ids"]


def test_table_validation_matches_golden():
    expected = PRICING["tables"]["validate"]
    assert {
        tid: validate_rate_table(t) for tid, t in sorted(ALL_TABLES.items())
    } == expected


def test_rental_columns_match_golden():
    expected = PRICING["tables"]["rental_columns"]
    actual = {
        tid: [c.key for c in t.columns if is_rental_car_column(c)]
        for tid, t in sorted(ALL_TABLES.items())
    }
    assert actual == expected


def test_eligible_columns_match_golden():
    expected = PRICING["tables"]["eligible"]
    actual = {
        tid: {age: [c.key for c in eligible_columns(t, int(age))] for age in ages}
        for tid, t in sorted(ALL_TABLES.items())
        for ages in [expected[tid]]
    }
    assert actual == expected


@pytest.mark.parametrize(
    "case",
    PRICING["tables"]["lookups"],
    ids=[
        f"{c['table_id']}-{c['column']}-{c['days']}"
        for c in PRICING["tables"]["lookups"]
    ],
)
def test_lookup_price_matches_golden(case):
    try:
        actual = {
            "price": lookup_price(
                MAIN_TABLES[case["table_id"]], case["column"], case["days"]
            )
        }
    except Exception as e:  # noqa: BLE001
        actual = error_of(e)
    assert actual == case["expected"]


# ---- profile ----


@pytest.mark.parametrize("case", PROFILE["merge"], ids=ids(PROFILE["merge"]))
def test_merge_patch_matches_golden(case):
    profile, changes = merge_patch(
        TripProfile(**case["profile"]), TripProfilePatch(**case["patch"])
    )
    assert {"profile": profile.model_dump(), "changes": changes} == case["expected"]


@pytest.mark.parametrize("case", PROFILE["checks"], ids=ids(PROFILE["checks"]))
def test_missing_and_validate_match_golden(case):
    profile = TripProfile(**case["profile"])
    assert missing_fields(profile) == case["missing"]
    assert validate_profile(profile) == case["validate"]


@pytest.mark.parametrize(
    "case",
    PROFILE["regions"],
    ids=[c["destination"] or "empty" for c in PROFILE["regions"]],
)
def test_region_of_matches_golden(case):
    assert list(region_of(case["destination"])) == case["expected"]


@pytest.mark.parametrize(
    "case", PROFILE["requirements"], ids=ids(PROFILE["requirements"])
)
def test_requirements_for_matches_golden(case):
    req, reasons = requirements_for(TripProfile(**case["profile"]))
    assert {"requirement": asdict(req), "reasons": reasons} == case["expected"]


# ---- recommend ----


def rec_of(case):
    return build_recommendation(
        TripProfile(**case["profile"]), top_n=case["top_n"], warn_fn=fake_warn
    )


@pytest.mark.parametrize("case", RECOMMEND, ids=ids(RECOMMEND))
def test_build_recommendation_matches_golden(case):
    rec = rec_of(case)
    actual = {
        "to_dict": rec.to_dict(),
        "numbers": sorted(rec.numbers(), key=int),
        "requirement": asdict(rec.requirement),
        "requirement_reasons": rec.requirement_reasons,
        "assumptions": rec.assumptions,
        "group_names": list(rec.groups),
    }
    assert jsonable(actual) == case["expected"]


# ---- narrate ----

RECOMMEND_BY_ID = {c["id"]: c for c in RECOMMEND}


@pytest.mark.parametrize(
    "case",
    NARRATE["extract_numbers"],
    ids=[repr(c["text"]) for c in NARRATE["extract_numbers"]],
)
def test_extract_numbers_matches_golden(case):
    assert sorted(extract_numbers(case["text"]), key=int) == case["expected"]


@pytest.mark.parametrize(
    "case", NARRATE["cases"], ids=ids(NARRATE["cases"], "recommend_case")
)
def test_narrate_matches_golden(case):
    rec = rec_of(RECOMMEND_BY_ID[case["recommend_case"]])
    template = render_template(rec)
    assert template == case["template"]
    assert render_report(rec, template) == case["report"]
    assert render_report(rec, "自訂本文") == case["report_custom_body"]
    for probe in case["probes"]:
        assert check_numbers(probe["text"], rec) == probe["check_numbers"]

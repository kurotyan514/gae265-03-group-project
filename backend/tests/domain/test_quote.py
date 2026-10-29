import pytest
from app.domain.pricing.quote import Requirement, Traveler, quote
from app.domain.pricing.tables import load_main_tables

TABLES = load_main_tables()
万 = 10_000


def _only(*ids):
    return {i: TABLES[i] for i in ids}


def _plan(plans, table_id):
    return next(p for p in plans if p.table_id == table_id)


def _reason(unavailable, table_id):
    return next(u for u in unavailable if u.table_id == table_id).reason


def test_fubon_attach1_cheapest_meeting_requirement():
    plans, _ = quote(
        5,
        [Traveler(30)],
        Requirement(illness_medical=50 * 万, accident_medical=20 * 万),
    )
    p = _plan(plans, "fubon_attach1_no_infectious")
    assert p.travelers[0].column_key == "p1_500"
    assert p.total == 979


def test_rental_car_picks_car_column():
    plans, _ = quote(
        5,
        [Traveler(30, rents_car=True)],
        Requirement(illness_medical=50 * 万, accident_medical=20 * 万),
    )
    p = _plan(plans, "fubon_attach1_no_infectious")
    assert p.travelers[0].column_key == "p1_500_car"
    assert p.total == 1079


def test_cathay_known_cells():
    cathay = _only("cathay_u3_no_infectious")
    p = quote(5, [Traveler(30)], tables=cathay)[0][0]
    assert (p.travelers[0].column_key, p.total) == ("c01", 975)
    p = quote(5, [Traveler(30)], Requirement(accident_death=500 * 万), tables=cathay)[
        0
    ][0]
    assert (p.travelers[0].column_key, p.total) == ("c03", 1192)
    p = quote(35, [Traveler(30)], tables=cathay)[0][0]
    assert (p.travelers[0].column_key, p.total) == ("c01", 2480)
    p = quote(10, [Traveler(30)], tables=_only("cathay_u3_infectious"))[0][0]
    assert (p.travelers[0].column_key, p.total) == ("c01", 1339)


def test_days_not_in_table_is_unavailable_not_rounded():
    plans, unavailable = quote(33, [Traveler(30)])
    assert "cathay_u3_no_infectious" not in {p.table_id for p in plans}
    reason = _reason(unavailable, "cathay_u3_no_infectious")
    assert "30" in reason and "35" in reason
    for days in (1, 11):
        reason = _reason(quote(days, [Traveler(30)])[1], "fubon_attach1_no_infectious")
        assert "2" in reason and "10" in reason


def test_multi_traveler_sums_by_each_age_band():
    plans, _ = quote(
        5, [Traveler(30), Traveler(8)], Requirement(illness_medical=30 * 万)
    )
    p = _plan(plans, "fubon_attach1_no_infectious")
    assert [t.column_key for t in p.travelers] == ["p1_300", "p1_child"]
    assert p.total == 688 + 430 == 1118


def test_one_traveler_without_column_makes_whole_table_unavailable():
    plans, unavailable = quote(5, [Traveler(30), Traveler(8)])
    assert not any(p.table_id.startswith("cathay") for p in plans)
    assert "第 2 位旅客（8 歲）" in _reason(unavailable, "cathay_u3_no_infectious")


def test_age_over_limit_for_requirement():
    plans, unavailable = quote(5, [Traveler(75)], Requirement(accident_death=500 * 万))
    assert "fubon_attach1_no_infectious" not in {p.table_id for p in plans}
    assert "意外身故失能" in _reason(unavailable, "fubon_attach1_no_infectious")


def test_none_price_column_is_skipped_with_note():
    plans, _ = quote(
        5,
        [Traveler(30)],
        Requirement(accident_death=300 * 万, illness_medical=150 * 万),
        tables=_only("fubon_general_no_infectious"),
    )
    p = plans[0]
    assert (p.travelers[0].column_key, p.total) == ("g3_500", 1369)
    assert any("g3_300" in n and "1,17" in n for n in p.notes)


def test_cathay_age_limit_note():
    plans, _ = quote(5, [Traveler(30)], tables=_only("cathay_u3_no_infectious"))
    assert any("未載明投保年齡上限" in n for n in plans[0].notes)


def test_infectious_filter():
    both = {p.infectious_covered for p in quote(5, [Traveler(30)])[0]}
    assert both == {True, False}
    yes = quote(5, [Traveler(30)], Requirement(infectious=True))[0]
    assert yes and all(p.infectious_covered for p in yes)
    no = quote(5, [Traveler(30)], Requirement(infectious=False))[0]
    assert no and not any(p.infectious_covered for p in no)


def test_results_sorted_by_total():
    totals = [p.total for p in quote(5, [Traveler(30)])[0]]
    assert totals == sorted(totals)


@pytest.mark.parametrize(
    "days, travelers",
    [
        (5, []),
        (5, [Traveler(30)] * 5),
        (5, [Traveler(-1)]),
        (5, [Traveler(30.5)]),  # pyright: ignore[reportArgumentType]
        (5, [Traveler(121)]),
        (0, [Traveler(30)]),
    ],
)
def test_invalid_inputs(days, travelers):
    with pytest.raises(ValueError):
        quote(days, travelers)


def test_unsatisfiable_requirement_returns_empty_not_error():
    plans, unavailable = quote(
        5, [Traveler(30)], Requirement(illness_medical=5_000 * 万)
    )
    assert plans == []
    assert len(unavailable) == len(TABLES)

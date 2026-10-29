from app.domain.pricing.tables import (
    eligible_columns,
    is_rental_car_column,
    load_main_tables,
)


def test_load_main_tables_excludes_addons():
    tables = load_main_tables()
    assert set(tables) == {
        "cathay_u3_infectious",
        "cathay_u3_no_infectious",
        "fubon_attach1_no_infectious",
        "fubon_attach2_infectious",
        "fubon_general_infectious",
        "fubon_general_no_infectious",
    }


def _keys(table, age):
    return [c.key for c in eligible_columns(table, age)]


def test_eligible_columns_age_boundaries():
    t = load_main_tables()["fubon_attach1_no_infectious"]
    assert _keys(t, 14) == ["p1_child", "p2_child"]
    assert "p1_200" in _keys(t, 15) and "p1_child" not in _keys(t, 15)
    assert "p1_500" in _keys(t, 74)
    assert "p1_500" not in _keys(t, 75) and "p1_300" in _keys(t, 75)
    assert "p1_300" in _keys(t, 79)
    assert _keys(t, 80) == []


def test_cathay_has_no_child_columns():
    t = load_main_tables()["cathay_u3_no_infectious"]
    assert eligible_columns(t, 14) == []
    assert len(eligible_columns(t, 15)) == 15


def test_rental_car_columns():
    tables = load_main_tables()
    fubon = tables["fubon_attach1_no_infectious"]
    car = {c.key for c in fubon.columns if is_rental_car_column(c)}
    assert car == {
        "p1_500_car",
        "p1_1000_car",
        "p2_500_car",
        "p2_1000_car",
        "p2_1500_car",
    }
    cathay = tables["cathay_u3_no_infectious"]
    assert not any(is_rental_car_column(c) for c in cathay.columns)

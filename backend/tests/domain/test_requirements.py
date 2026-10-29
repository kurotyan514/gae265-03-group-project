from app.domain.recommend.profile import TripProfile
from app.domain.recommend.requirements import requirements_for

萬 = 10000


def profile(**kw):
    base = {
        "destination": "日本",
        "region": "japan_europe_us",
        "days": 5,
        "ages": [30],
        "travelers": 1,
        "activities": [],
        "wants_infectious": False,
    }
    base.update(kw)
    return TripProfile(**base)


def test_japan_requires_500k_illness():
    req, _ = requirements_for(profile())
    assert req.illness_medical == 50 * 萬


def test_other_region_requires_300k():
    req, _ = requirements_for(profile(region="other"))
    assert req.illness_medical == 30 * 萬


def test_unknown_region_treated_as_strict():
    req, _ = requirements_for(profile(region=None))
    assert req.illness_medical == 50 * 萬


def test_no_activity_accident_medical_200k():
    req, _ = requirements_for(profile())
    assert req.accident_medical == 20 * 萬


def test_ski_raises_accident_medical_to_300k():
    req, _ = requirements_for(profile(activities=["滑雪"]))
    assert req.accident_medical == 30 * 萬


def test_dive_also_raises():
    req, _ = requirements_for(profile(activities=["潛水"]))
    assert req.accident_medical == 30 * 萬


def test_other_activity_does_not_raise():
    req, _ = requirements_for(profile(activities=["浮潛"]))
    assert req.accident_medical == 20 * 萬


def test_death_has_no_minimum():
    req, _ = requirements_for(profile(travelers=2, ages=[30, 28]))
    assert req.accident_death == 0


def test_family_adds_death_reminder():
    _, solo = requirements_for(profile())
    _, family = requirements_for(profile(travelers=2, ages=[30, 28]))
    assert not any("意外身故失能" in s for s in solo)
    assert any("意外身故失能" in s for s in family)


def test_infectious_follows_profile():
    assert requirements_for(profile(wants_infectious=True))[0].infectious is True
    assert requirements_for(profile(wants_infectious=False))[0].infectious is False
    assert (
        requirements_for(profile(wants_infectious=None, infectious_undecided=True))[
            0
        ].infectious
        is None
    )


def test_reasons_mention_numbers():
    _, reasons = requirements_for(profile(activities=["滑雪"]))
    text = "\n".join(reasons)
    assert "50 萬" in text and "30 萬" in text


# ---- 使用者要求調整保額 ----


def test_one_step_raises_medical_to_next_ladder_level():
    req, _ = requirements_for(profile(activities=["滑雪"], coverage_steps=1))
    assert req.illness_medical == 100 * 萬  # 50 → 100
    assert req.accident_medical == 50 * 萬  # 30 → 50


def test_two_steps_and_ladder_top():
    req, _ = requirements_for(profile(coverage_steps=2))
    assert req.illness_medical == 200 * 萬
    assert req.accident_medical == 50 * 萬  # 20 → 30 → 50，一級一級往上
    top, _ = requirements_for(profile(coverage_steps=99))
    assert top.illness_medical == 200 * 萬  # 階梯最高 200 萬，不再往上
    assert top.accident_medical == 200 * 萬


def test_explicit_minimum_overrides_threshold():
    req, reasons = requirements_for(
        profile(min_illness_medical=80 * 萬, min_accident_death=500 * 萬)
    )
    assert req.illness_medical == 80 * 萬
    assert req.accident_death == 500 * 萬
    assert any("依你的要求" in r and "80 萬" in r for r in reasons)


def test_steps_reasons_mention_request():
    _, reasons = requirements_for(profile(coverage_steps=1))
    assert any("依你的要求" in r and "100 萬" in r for r in reasons)

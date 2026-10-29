from app.domain.recommend.profile import (
    QUESTIONS,
    TripProfile,
    TripProfilePatch,
    merge_patch,
    missing_fields,
    normalize_activity,
    validate_profile,
)


def test_merge_ignores_none_fields():
    new, changes = merge_patch(TripProfile(days=5), TripProfilePatch())
    assert new.days == 5
    assert changes == []


def test_merge_overwrites_with_value_and_reports_change():
    new, changes = merge_patch(TripProfile(days=5), TripProfilePatch(days=6))
    assert new.days == 6
    assert changes == ["days: 5 → 6"]


def test_merge_no_activities_means_empty_list():
    new, _ = merge_patch(TripProfile(), TripProfilePatch(no_activities=True))
    assert new.activities == []
    new, _ = merge_patch(TripProfile(), TripProfilePatch(activities=["滑雪"]))
    assert new.activities == ["滑雪"]
    new, _ = merge_patch(
        TripProfile(), TripProfilePatch(activities=["滑雪"], no_activities=True)
    )
    assert new.activities == ["滑雪"]  # 兩者都有時以 activities 為準


def test_activities_are_normalized_and_deduped():
    assert normalize_activity(" 滑雪板 ") == "滑雪"
    assert normalize_activity("浮潛") == "浮潛"  # 浮潛不是潛水，原樣保留
    new, _ = merge_patch(
        TripProfile(), TripProfilePatch(activities=["滑雪板", "滑雪", "浮潛"])
    )
    assert new.activities == ["滑雪", "浮潛"]


def test_merge_infectious_unsure():
    new, _ = merge_patch(TripProfile(), TripProfilePatch(infectious_unsure=True))
    assert new.wants_infectious is None
    assert new.infectious_undecided is True
    assert "wants_infectious" not in missing_fields(new)
    # 之後使用者真的決定了，就不再是「未決定」
    new, _ = merge_patch(new, TripProfilePatch(wants_infectious=True))
    assert new.wants_infectious is True
    assert new.infectious_undecided is False


def test_unsure_wins_when_model_also_fills_wants_infectious():
    # 小模型（gemma4:e4b）聽到「不知道」時會同時填 unsure 和 wants=True；以「不知道」為準，兩種都比較
    new, _ = merge_patch(
        TripProfile(), TripProfilePatch(infectious_unsure=True, wants_infectious=True)
    )
    assert new.wants_infectious is None
    assert new.infectious_undecided is True
    # 已經決定過的就維持原決定，不被矛盾的輸出蓋掉
    known, _ = merge_patch(
        TripProfile(wants_infectious=False),
        TripProfilePatch(infectious_unsure=True, wants_infectious=True),
    )
    assert known.wants_infectious is False


def test_missing_fields_order():
    assert missing_fields(TripProfile()) == [
        "destination",
        "days",
        "ages",
        "activities",
        "wants_infectious",
    ]
    partial = TripProfile(destination="日本", days=5)
    assert missing_fields(partial) == ["ages", "activities", "wants_infectious"]


def test_missing_ages_when_count_mismatch():
    assert "ages" in missing_fields(TripProfile(travelers=2, ages=[30]))
    # 沒說人數時，人數由年齡個數推得
    assert "ages" not in missing_fields(TripProfile(travelers=None, ages=[30]))


def test_complete_profile_has_no_missing():
    p = TripProfile(
        destination="日本", days=5, ages=[30], activities=[], wants_infectious=False
    )
    assert missing_fields(p) == []


def test_validation_rejects_bad_values():
    new, changes = merge_patch(TripProfile(days=5), TripProfilePatch(days=0))
    assert new.days == 5
    assert any("已忽略" in c for c in changes)
    new, _ = merge_patch(TripProfile(), TripProfilePatch(days=-2))
    assert new.days is None
    new, changes = merge_patch(TripProfile(), TripProfilePatch(ages=[-3]))
    assert new.ages is None
    assert any("已忽略" in c for c in changes)
    new, _ = merge_patch(TripProfile(), TripProfilePatch(ages=[130]))
    assert new.ages is None


def test_more_than_four_travelers_message():
    for profile in (TripProfile(ages=[20, 21, 22, 23, 24]), TripProfile(travelers=5)):
        message = validate_profile(profile)
        assert message is not None
        assert "最多 4 人" in message
    assert validate_profile(TripProfile(ages=[20, 21, 22, 23])) is None


def test_questions_cover_all_fields():
    assert set(QUESTIONS) == {
        "destination",
        "days",
        "ages",
        "activities",
        "wants_infectious",
    }
    assert "傳染病" in QUESTIONS["wants_infectious"]


# ---- 推薦後的調整：保障上調與自訂保額 ----


def test_raise_coverage_increments_steps_with_cap():
    from app.domain.recommend.profile import (
        MAX_COVERAGE_STEPS,
        TripProfile,
        TripProfilePatch,
        merge_patch,
    )

    profile = TripProfile()
    for expected in range(1, MAX_COVERAGE_STEPS + 1):
        profile, changes = merge_patch(profile, TripProfilePatch(raise_coverage=True))
        assert profile.coverage_steps == expected
        assert changes
    profile, changes = merge_patch(profile, TripProfilePatch(raise_coverage=True))
    assert profile.coverage_steps == MAX_COVERAGE_STEPS  # 不會無限上調


def test_explicit_coverage_in_wan_converted_to_yuan():
    from app.domain.recommend.profile import TripProfile, TripProfilePatch, merge_patch

    patch = TripProfilePatch(
        illness_medical_wan=100, accident_medical_wan=50, accident_death_wan=500
    )
    profile, changes = merge_patch(TripProfile(), patch)
    assert profile.min_illness_medical == 1_000_000
    assert profile.min_accident_medical == 500_000
    assert profile.min_accident_death == 5_000_000
    assert len(changes) == 3


def test_unreasonable_explicit_coverage_ignored():
    from app.domain.recommend.profile import TripProfile, TripProfilePatch, merge_patch

    patch = TripProfilePatch(
        illness_medical_wan=0, accident_medical_wan=-5, accident_death_wan=99999
    )
    profile, changes = merge_patch(TripProfile(), patch)
    assert profile.min_illness_medical is None
    assert profile.min_accident_medical is None
    assert profile.min_accident_death is None
    assert any("已忽略" in c for c in changes)


def test_unchanged_patch_produces_no_changes():
    from app.domain.recommend.profile import TripProfile, TripProfilePatch, merge_patch

    profile = TripProfile(destination="日本", days=5)
    _, changes = merge_patch(profile, TripProfilePatch(days=5))
    assert changes == []

import json

from app.domain.recommend.regions import region_of


def test_known_destinations():
    assert region_of("日本北海道") == ("japan_europe_us", False)
    assert region_of("泰國") == ("other", False)
    assert region_of("韓國首爾") == ("other", False)
    assert region_of("法國巴黎") == ("japan_europe_us", False)


def test_unknown_destination_is_conservative_and_flagged():
    assert region_of("不丹") == ("japan_europe_us", True)


def test_matches_longest_alias_first(tmp_path):
    path = tmp_path / "regions.json"
    path.write_text(
        json.dumps(
            {"japan_europe_us": ["大洋洲"], "other": ["大洋洲小島"]}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    assert region_of("大洋洲小島自由行", path) == ("other", False)
    assert region_of("大洋洲本島", path) == ("japan_europe_us", False)


def test_empty_destination_is_unknown():
    assert region_of("") == ("japan_europe_us", True)
    assert region_of("   ") == ("japan_europe_us", True)

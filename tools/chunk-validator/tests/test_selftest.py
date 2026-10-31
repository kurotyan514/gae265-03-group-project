from validator.selftest import run_selftest, summarize, to_cn


def test_to_cn():
    assert [to_cn(n) for n in (1, 10, 11, 20, 25)] == [
        "一",
        "十",
        "十一",
        "二十",
        "二十五",
    ]


def test_every_planted_error_is_caught_on_fixture(make_ctx):
    rows = run_selftest(make_ctx(), reps=2)
    missed = [r for r in rows if r["結果"] != "抓到（FAIL）"]
    assert not missed, missed
    assert summarize(rows)["偵錯率"] == "100%"
    # 測試用假資料只有 1 個險種、3 條，需要「另一個險種」或較長內文的錯誤類型找不到目標；
    # 全部 16 種在真實資料上用 `python -m validator selftest` 驗證
    assert len({r["錯誤類型"] for r in rows}) >= 10

"""PDF 字型把「六」「金」等字編成 CJK 相容字時，標題仍要讀得到（票 #113）。"""

from app.ingest.verify.baseline import baseline_from_pages
from app.ingest.verify.profiles import load_profiles
from app.ingest.verify.textutil import fold_compat_ideographs

SIX = "六"  # 相容字的「六」，外觀與一般的「六」相同
GOLD = "金"  # 相容字的「金」

PAGES = [
    [
        "第五條【身故保險金的給付】",
        "被保險人死亡時，本公司給付身故保險金。",
        f"第{SIX}條【失能保險{GOLD}的給付】",
        "被保險人失能時，本公司給付失能保險金。",
        "第七條【燒燙傷保險金的給付】",
        "被保險人燒燙傷時，本公司給付保險金。",
    ]
]


def test_折疊相容字_其他字元不動() -> None:
    assert (
        fold_compat_ideographs(f"第{SIX}條【保險{GOLD}】，ＡＢ１")
        == "第六條【保險金】，ＡＢ１"
    )


def test_標題裡有相容字的條文也讀得到() -> None:
    baseline = baseline_from_pages(PAGES, PAGES, load_profiles()["安達產物"])

    assert sorted(baseline.articles) == [5, 6, 7]
    article = baseline.articles[6]
    assert article.a and article.a.title == "【失能保險金的給付】"
    assert article.b and "被保險人失能時" in article.b.text

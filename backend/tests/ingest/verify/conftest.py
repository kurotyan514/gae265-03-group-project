"""測試用的假資料：一個虛構險種 X001，三條條文。不需要網路，也不需要真的 PDF。"""

import pytest
from app.ingest.verify import ArticleInput, VerifySpec
from app.ingest.verify.baseline import Baseline, baseline_from_pages
from app.ingest.verify.profiles import CompanyProfile, load_profiles

PAGES = [
    [
        "測試產物保險公司",
        "測試產物旅行平安保險",
        "第一條 契約構成",
        "本保險單條款為本契約構成部分。",
        "第二條 承保範圍",
        "被保險人於保險期間內因意外事故，本公司依第三條約定給付。",
        "1",
    ],
    [
        "第三條",
        "理賠文件",
        "被保險人申請理賠時應檢附理賠申請書。",
        "並應於事故發生後七日內通知本公司。",
        "附表一 給付比例表",
        "一級 百分之百",
        "2",
    ],
]

SPEC = VerifySpec(code="X001", name="旅行平安保險", company="測試產物")


def make_articles() -> list[ArticleInput]:
    return [
        ArticleInput(
            article_no=1,
            title="契約構成",
            content="本保險單條款為本契約構成部分。",
            page_start=1,
            page_end=1,
        ),
        ArticleInput(
            article_no=2,
            title="承保範圍",
            content="被保險人於保險期間內因意外事故，本公司依第三條約定給付。",
            page_start=1,
            page_end=1,
        ),
        ArticleInput(
            article_no=3,
            title="理賠文件",
            content="被保險人申請理賠時應檢附理賠申請書。\n並應於事故發生後七日內通知本公司。",
            page_start=2,
            page_end=2,
        ),
    ]


@pytest.fixture
def profiles() -> dict[str, CompanyProfile]:
    return load_profiles()


@pytest.fixture
def baseline(profiles: dict[str, CompanyProfile]) -> Baseline:
    return baseline_from_pages(PAGES, PAGES, profiles["default"])

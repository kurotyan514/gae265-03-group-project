"""測試用的假資料：一個虛構險種 X001，三條條文。不需要網路，也不需要真的 PDF。"""

from pathlib import Path

import pytest

from validator.baseline import baseline_from_pages
from validator.config import Insurance, Settings, load_profiles
from validator.models import Context

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

ITEMS = [
    {
        "no": 1,
        "title": "契約構成",
        "content": "本保險單條款為本契約構成部分。",
        "pages": (1, 1),
    },
    {
        "no": 2,
        "title": "承保範圍",
        "content": "被保險人於保險期間內因意外事故，本公司依第三條約定給付。",
        "pages": (1, 1),
    },
    {
        "no": 3,
        "title": "理賠文件",
        "content": "被保險人申請理賠時應檢附理賠申請書。\n並應於事故發生後七日內通知本公司。",
        "pages": (2, 2),
    },
]


def make_items() -> list[dict]:
    return [
        {
            "insurance_code": "X001",
            "insurance_name": "旅行平安保險",
            "article_no": it["no"],
            "chapter": "",
            "title": it["title"],
            "content": it["content"],
            "section": None,
            "source_file": "X001.pdf",
            "page_start": it["pages"][0],
            "page_end": it["pages"][1],
            "embedding_models": ["test-model"],
            "embedding_dimensions": 8,
        }
        for it in ITEMS
    ]


@pytest.fixture
def profiles():
    return load_profiles()


@pytest.fixture
def baseline(profiles):
    return baseline_from_pages(
        "X001", Path("X001.pdf"), "abc", PAGES, PAGES, profiles["default"]
    )


@pytest.fixture
def make_ctx(baseline, profiles):
    registry = {
        "X001": Insurance(
            "X001", "測試產物", "旅行平安保險", "測試產物/X001.pdf", pdf_sha256="abc"
        )
    }

    def _make(items=None, baselines=None):
        return Context(
            items if items is not None else make_items(),
            registry,
            {"X001": baseline} if baselines is None else baselines,
            {},
            Settings(api_base_url="http://test", long_chunk_chars=1200),
            profiles,
        )

    return _make

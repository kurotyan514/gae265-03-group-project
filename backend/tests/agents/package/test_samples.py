"""/dev/package 頁的範例：每個範例交給 7 號的 build，呈現它要展示的情況。

範例內容都是虛構的（ADR-0009）。
"""

import re

from app.agents.package import GmailClaimPackager
from app.agents.package.samples import SAMPLES


def _sample(key: str):
    return next(s for s in SAMPLES if s.key == key)


def _blanks(text: str) -> set[str]:
    """信裡的空格項目：「（請填寫＋項目）」的項目（與前端的約定）。"""
    return set(re.findall(r"（請填寫([^）]+)）", text))


async def test_每個範例都有名稱與說明_代號不重複_而且產生得出送件包() -> None:
    assert SAMPLES
    assert len({s.key for s in SAMPLES}) == len(SAMPLES)
    for sample in SAMPLES:
        assert sample.title and sample.description, sample.key

        package = await GmailClaimPackager().build(sample.context)

        assert package.subject and package.body, sample.key


async def test_資料齊全的範例只剩平台沒有的三格() -> None:
    package = await GmailClaimPackager().build(_sample("complete").context)

    assert _blanks(package.subject + package.body) == {
        "被保險人姓名",
        "保單號碼",
        "聯絡電話",
    }
    assert package.attachments
    assert package.missing_todo_ids == []


async def test_資料都抓不到的範例出現全部十個空格() -> None:
    package = await GmailClaimPackager().build(_sample("all_missing").context)

    assert _blanks(package.subject + package.body) == {
        "被保險人姓名",
        "保險公司",
        "保額",
        "保險期間",
        "保單號碼",
        "事故類型",
        "日期",
        "地點",
        "經過",
        "聯絡電話",
    }


async def test_沒有附件的範例寫相關文件另行提供與附件清單無() -> None:
    package = await GmailClaimPackager().build(_sample("no_attachments").context)

    assert package.attachments == []
    assert "相關文件另行提供" in package.body
    assert "附件清單\n・（無）" in package.body


async def test_有未附文件的範例列出未隨信附上的文件() -> None:
    package = await GmailClaimPackager().build(_sample("without_document").context)

    assert "未隨信附上的文件\n・" in package.body
    assert package.attachments  # 還有其他附件


async def test_跨年的範例保險期間寫出迄日的年份() -> None:
    package = await GmailClaimPackager().build(_sample("cross_year").context)

    assert package.subject.endswith("－2026/12/30～2027/01/03")

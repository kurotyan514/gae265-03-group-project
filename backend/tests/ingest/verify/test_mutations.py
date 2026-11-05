"""驗證器自我測試：故意把乾淨的條文弄壞一個地方，驗證器必須抓到（FAIL），並由預期的那一項檢查抓到。

原本獨立工具用真實資料隨機埋 16 種錯；這裡改成固定的小資料，每種錯誤一個測試案例，
讓每次 CI 都確認驗證器沒有退步。（險種代碼錯置、來源檔錯誤、險種名稱被改、沒有向量
這四種屬於登記表與 API 的檢查，上傳流程不適用。）
"""

from collections.abc import Callable

import pytest
from app.ingest.verify import ArticleInput, Status, verify_with_baseline
from app.ingest.verify.baseline import Baseline

from tests.ingest.verify.conftest import SPEC, make_articles

Mutation = Callable[[list[ArticleInput]], list[ArticleInput]]


def by_no(arts: list[ArticleInput], no: int) -> ArticleInput:
    return next(a for a in arts if a.article_no == no)


def delete_article(arts: list[ArticleInput]) -> list[ArticleInput]:
    return [a for a in arts if a.article_no != 2]


def duplicate_article(arts: list[ArticleInput]) -> list[ArticleInput]:
    return [*arts, by_no(arts, 2).model_copy()]


def unexpected_article(arts: list[ArticleInput]) -> list[ArticleInput]:
    return [*arts, by_no(arts, 2).model_copy(update={"article_no": 99})]


def change_char(arts: list[ArticleInput]) -> list[ArticleInput]:
    a = by_no(arts, 2)
    a.content = a.content.replace("意外", "意甲")
    return arts


def change_number(arts: list[ArticleInput]) -> list[ArticleInput]:
    a = by_no(arts, 3)
    a.content = a.content.replace("七日", "十日")
    return arts


def drop_line(arts: list[ArticleInput]) -> list[ArticleInput]:
    a = by_no(arts, 3)
    a.content = a.content.split("\n")[0]
    return arts


def wrong_title(arts: list[ArticleInput]) -> list[ArticleInput]:
    by_no(arts, 2).title += "及給付"
    return arts


def truncate_tail(arts: list[ArticleInput]) -> list[ArticleInput]:
    a = by_no(arts, 3)
    a.content = a.content.rsplit("\n", 1)[0]
    return arts


def tail_to_next(arts: list[ArticleInput]) -> list[ArticleInput]:
    # 第二條只有一行，用第三條的第一行移到第二條結尾比較貼近「切到隔壁」的樣子
    a2, a3 = by_no(arts, 2), by_no(arts, 3)
    first, rest = a3.content.split("\n", 1)
    a2.content += "\n" + first
    a3.content = rest
    return arts


def inject_next(arts: list[ArticleInput]) -> list[ArticleInput]:
    a2, a3 = by_no(arts, 2), by_no(arts, 3)
    a2.content += f"\n第三條 {a3.title}\n{a3.content.splitlines()[0]}"
    return arts


def title_in_body(arts: list[ArticleInput]) -> list[ArticleInput]:
    a = by_no(arts, 1)
    a.content = a.title + "\n" + a.content
    a.title = ""
    return arts


def wrong_page(arts: list[ArticleInput]) -> list[ArticleInput]:
    a = by_no(arts, 3)
    a.page_start = a.page_end = 1
    return arts


MUTATIONS: dict[str, tuple[Mutation, str]] = {
    "刪掉一條": (delete_article, "completeness"),
    "重複一條": (duplicate_article, "completeness"),
    "多一條不存在的條號": (unexpected_article, "completeness"),
    "改一個字": (change_char, "accuracy"),
    "改一個數字": (change_number, "accuracy"),
    "少一行": (drop_line, "accuracy"),
    "標題錯誤": (wrong_title, "accuracy"),
    "結尾被截斷": (truncate_tail, "boundary"),
    "結尾切到下一條": (tail_to_next, "boundary"),
    "混入下一條": (inject_next, "boundary"),
    "標題被當內文": (title_in_body, "boundary"),
    "頁碼錯誤": (wrong_page, "traceability"),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_validator_catches_planted_error(name: str, baseline: Baseline) -> None:
    mutate, expected_check = MUTATIONS[name]
    arts = mutate(make_articles())
    report = verify_with_baseline(baseline, arts, SPEC)
    fails = [f for f in report.findings if f.status == Status.FAIL]
    assert fails, f"漏抓：{name}"
    assert expected_check in {f.check for f in fails}, (
        f"{name}：預期由 {expected_check} 抓到，實際是 {sorted({f.check for f in fails})}"
    )

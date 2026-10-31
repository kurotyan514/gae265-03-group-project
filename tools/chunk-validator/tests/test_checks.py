"""六項驗證：正常資料要全部通過；每種錯誤要被正確的規則抓到。"""

from tests.conftest import make_items
from validator.models import Status
from validator.runner import chunk_table, run_checks


def problems(ctx, status=Status.FAIL):
    return {(f.rule, f.article_no) for f in run_checks(ctx) if f.status == status}


def item(items, no):
    return next(i for i in items if i["article_no"] == no)


def test_clean_data_has_no_fail_or_warning(make_ctx):
    ctx = make_ctx()
    findings = run_checks(ctx)
    assert not [f for f in findings if f.status in (Status.FAIL, Status.WARNING)]
    assert {r["整體"] for r in chunk_table(ctx, findings)} == {"PASS"}


def test_format_only_difference_passes(make_ctx):
    items = make_items()
    item(items, 3)["content"] = (
        "被保險人申請理賠時 應檢附理賠申請書。並應於事故發生後七日內通知本公司。"
    )
    assert problems(make_ctx(items)) == set()


def test_missing_article(make_ctx):
    items = [i for i in make_items() if i["article_no"] != 2]
    assert ("C1-missing", 2) in problems(make_ctx(items))


def test_duplicate_and_unexpected(make_ctx):
    items = make_items()
    items.append(dict(item(items, 1)))
    items.append({**item(items, 1), "article_no": 8})
    found = problems(make_ctx(items))
    assert ("C2-duplicate", 1) in found
    assert ("C3-unexpected", 8) in found


def test_changed_word_is_content_fail(make_ctx):
    items = make_items()
    item(items, 3)["content"] = item(items, 3)["content"].replace("七日", "十日")
    assert ("A2-content", 3) in problems(make_ctx(items))


def test_wrong_title(make_ctx):
    items = make_items()
    item(items, 2)["title"] = "承保範圍說明"
    assert ("A1-title", 2) in problems(make_ctx(items))


def test_tail_moved_to_next_article(make_ctx):
    items = make_items()
    tail = "本公司依第三條約定給付。"
    item(items, 2)["content"] = "被保險人於保險期間內因意外事故，"
    item(items, 3)["content"] = tail + "\n" + item(items, 3)["content"]
    found = problems(make_ctx(items))
    assert ("B5-tail-in-next", 2) in found
    assert ("B3-head-from-prev", 3) in found


def test_head_moved_to_previous_article(make_ctx):
    items = make_items()
    item(items, 2)["content"] += "\n被保險人申請理賠時應檢附理賠申請書。"
    item(items, 3)["content"] = "並應於事故發生後七日內通知本公司。"
    found = problems(make_ctx(items))
    assert ("B6-tail-from-next", 2) in found
    assert ("B4-head-in-prev", 3) in found


def test_foreign_heading_inside_content(make_ctx):
    items = make_items()
    item(items, 2)["content"] += (
        "\n第三條 理賠文件\n被保險人申請理賠時應檢附理賠申請書。"
    )
    assert ("B1-foreign-heading", 2) in problems(make_ctx(items))


def test_legal_reference_is_not_boundary_error(make_ctx):
    # 第二條內文本來就有「依第三條約定」，正常資料不應出現 B1
    assert not {r for r in problems(make_ctx()) if r[0].startswith("B1")}


def test_title_in_body(make_ctx):
    items = make_items()
    item(items, 1)["content"] = "契約構成\n" + item(items, 1)["content"]
    item(items, 1)["title"] = ""
    found = problems(make_ctx(items))
    assert ("B2-no-title", 1) in found and ("B2-title-in-body", 1) in found


def test_wrong_insurance_name(make_ctx):
    items = make_items()
    for i in items:
        i["insurance_name"] = "旅遊不便險"
    found = problems(make_ctx(items))
    assert ("R1-name-mismatch", 1) in found and ("R2-name-not-in-pdf", 1) in found


def test_unregistered_insurance_is_warning_and_not_verified(make_ctx):
    items = make_items()
    for i in items:
        i["insurance_code"] = "NEW9"
    ctx = make_ctx(items)
    assert ("R0-unregistered", 1) in problems(ctx, Status.WARNING)
    assert ("C9-no-baseline", 1) in problems(ctx, Status.NOT_VERIFIED)
    # 沒有標準答案的條文絕不能是 PASS
    assert all(r["整體"] != "PASS" for r in chunk_table(ctx, run_checks(ctx)))


def test_wrong_page(make_ctx):
    items = make_items()
    item(items, 3)["page_start"] = item(items, 3)["page_end"] = 1
    assert ("T3-text-not-on-pages", 3) in problems(make_ctx(items))


def test_page_out_of_range_and_wrong_source(make_ctx):
    items = make_items()
    item(items, 1)["page_end"] = 9
    item(items, 2)["source_file"] = "OTHER.pdf"
    found = problems(make_ctx(items))
    assert ("T2-page-out-of-range", 1) in found and ("T1-source-file", 2) in found


def test_long_chunk_is_warning_not_fail(make_ctx):
    items = make_items()
    item(items, 1)["content"] = "甲" * 1300
    ctx = make_ctx(items)
    assert ("L1-long", 1) in problems(ctx, Status.WARNING)


def test_missing_embedding(make_ctx):
    items = make_items()
    item(items, 1)["embedding_models"] = []
    assert ("C5-no-embedding", 1) in problems(make_ctx(items))


def test_dataset_level_not_verified_items_are_reported(make_ctx):
    rules = {f.rule for f in run_checks(make_ctx()) if f.scope == "dataset"}
    assert {"T8-no-chunk-id", "T8-no-version", "R8-no-company-field"} <= rules


def test_change_matching_errata_is_warning_not_fail(make_ctx):
    from validator.config import Erratum

    items = make_items()
    item(items, 3)["content"] = item(items, 3)["content"].replace("七日", "十日")
    errata = {("X001", 3): [Erratum("X001", 3, "七日", "十日", "實際保單是十日")]}
    ctx = make_ctx(items)
    ctx.errata = errata
    assert ("A5-known-errata", 3) in problems(ctx, Status.WARNING)
    assert ("A2-content", 3) not in problems(ctx)


def test_errata_does_not_hide_other_changes(make_ctx):
    from validator.config import Erratum

    items = make_items()
    item(items, 3)["content"] = (
        item(items, 3)["content"]
        .replace("七日", "十日")
        .replace("理賠申請書", "申請書")
    )
    ctx = make_ctx(items)
    ctx.errata = {("X001", 3): [Erratum("X001", 3, "七日", "十日", "實際保單是十日")]}
    assert ("A2-content", 3) in problems(ctx)

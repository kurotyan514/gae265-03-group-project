"""險種在頁面中間才開始時，標準答案只取自己那一段（票 #96）。"""

from app.ingest.verify.baseline import SectionRange, only_section

PAGES = [
    ["甲險 條款", "第一條", "甲的內容"],
    ["甲的尾巴", "乙險 條款", "第一條", "乙的內容", "丙險 條款", "第一條", "丙的內容"],
    ["丙的第二頁"],
]


def test_起點頁丟掉標題行之前_終點頁只留下一個標題行之前() -> None:
    rng = SectionRange(2, "乙險條款", 2, "丙險 條款")  # 比對忽略空白

    assert only_section(PAGES, rng) == [
        [],
        ["乙險 條款", "第一條", "乙的內容"],
        [],
    ]


def test_最後一個區段到_PDF_結尾() -> None:
    rng = SectionRange(2, "丙險 條款")

    assert only_section(PAGES, rng) == [
        [],
        ["丙險 條款", "第一條", "丙的內容"],
        ["丙的第二頁"],
    ]


def test_中間跨頁的區段整頁保留() -> None:
    rng = SectionRange(1, "甲險 條款", 2, "乙險 條款")

    assert only_section(PAGES, rng) == [
        PAGES[0],
        ["甲的尾巴"],
        [],
    ]


def test_找不到標題行的那一頁不裁_寧可多留也不要裁掉本文() -> None:
    rng = SectionRange(2, "這個工具讀成別的樣子", 2, "也找不到")

    assert only_section(PAGES, rng)[1] == PAGES[1]

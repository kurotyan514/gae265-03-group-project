from app.policy.deidentify import (
    ADDRESS,
    EMAIL,
    ID_NO,
    NAME,
    PHONE,
    POLICY_NO,
    deidentify_pages,
)

from tests.policy.support import (
    FAKE_NAME,
    PII,
    SUMMARY_LAYOUT,
    SUMMARY_READING,
)


def test_no_fake_pii_survives_in_either_layout():
    out = deidentify_pages([SUMMARY_LAYOUT])[0]
    assert [p for p in PII if p in out] == []


def test_values_found_in_layout_text_are_masked_in_reading_order_text():
    """標籤與值在閱讀順序裡分成兩行，靠位置排序的文字找到值，再逐字取代。"""
    out = deidentify_pages([SUMMARY_READING], [SUMMARY_LAYOUT])[0]
    assert FAKE_NAME not in out
    assert out.count(NAME) == 2  # 標籤下一行與收據上各一次
    assert "050026CT200R3446" not in out


def test_text_other_than_masked_values_is_verbatim():
    """除遮蔽處外，內容逐字保留（包含金額這類數字）。"""
    out = deidentify_pages([SUMMARY_LAYOUT])[0]
    assert "T068 旅行平安保險  每一人死亡失能  6,000,000元" in out
    assert "要保人與被保人關係 :本人" in out  # 這個標籤的值不是姓名
    assert "免費申訴電話:0800-009-888" in out  # 公司的免付費專線不是個資
    for placeholder in (NAME, ID_NO, POLICY_NO, PHONE, EMAIL, ADDRESS):
        assert placeholder in out
    # 把占位文字還原成原文之外的字元應該一樣
    assert out.replace(NAME, "").replace(ID_NO, "").count("\n") == SUMMARY_LAYOUT.count(
        "\n"
    )


def test_placeholders_contain_no_digits():
    for placeholder in (NAME, ID_NO, POLICY_NO, PHONE, EMAIL, ADDRESS):
        assert not any(c.isdigit() for c in placeholder)


def test_clause_definitions_are_not_mistaken_for_names():
    text = "名詞定義\n被保險人：指以其身體或財物受保險契約保障之人。\n要保人：指對保險標的具有保險利益"
    assert deidentify_pages([text])[0] == text


def test_label_value_does_not_leak_into_the_next_line():
    """標籤後面是空的，下一行是另一個標籤：不能把下一行當成值。"""
    text = "保單號碼      :\n被保險人      : 王小明\n"
    out = deidentify_pages([text])[0]
    assert "被保險人" in out
    assert out.startswith("保單號碼      :\n")


def test_long_names_are_replaced_before_their_substrings():
    text = "被保險人 : 王小明\n要保人 : 小明\n王小明 與 小明"
    out = deidentify_pages([text])[0]
    assert "王" not in out
    assert "小明" not in out

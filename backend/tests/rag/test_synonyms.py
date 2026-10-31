from app.domain.rag.synonyms import SynonymRule, expand_with_synonyms, load_synonyms

RULES: list[SynonymRule] = [
    {"if_any": ["偷", "扒"], "add": ["竊盜", "強盜"]},
    {"if_any": ["賠", "補償"], "add": ["保險金", "給付"]},
    {"if_any": ["偷"], "add": ["竊盜"]},  # 重複的詞只加一次
]


def test_query_comes_first_and_matching_rules_append_their_words():
    assert (
        expand_with_synonyms("手機被偷會賠嗎", RULES)
        == "手機被偷會賠嗎 竊盜 強盜 保險金 給付"
    )


def test_no_match_leaves_the_query_unchanged():
    assert expand_with_synonyms("班機延誤", RULES) == "班機延誤"


def test_empty_rules_leave_the_query_unchanged():
    assert expand_with_synonyms("手機被偷", []) == "手機被偷"


def test_shipped_synonyms_file_has_the_12_rules_from_the_prototype():
    rules = load_synonyms()
    assert len(rules) == 12
    assert all(rule["if_any"] and rule["add"] for rule in rules)


def test_shipped_synonyms_bridge_colloquial_to_clause_wording():
    expanded = expand_with_synonyms("滑雪受傷，意外傷害醫療會不會賠？", load_synonyms())
    assert expanded.startswith("滑雪受傷，意外傷害醫療會不會賠？")
    assert {"競賽", "特技", "保險金", "給付"} <= set(expanded.split())

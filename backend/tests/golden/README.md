# 對照資料（golden）

第 1 階段（報價與推薦核心）的對照資料，由原型 `insurance_agent`（來源版本 `512c7b1`，產生日 2026-10-29）對固定輸入執行後存下。新實作要逐筆比對到完全一致；不一致時先查原因並回報，**不改這些檔案去配合新程式**（見 `docs/migration/insurance-agent/README.md` 規則 4）。

| 檔案 | 內容 |
| --- | --- |
| `pricing.json` | `quote()` 200 筆（天數、旅客、年齡邊界、租車、法傳、保額、輸入錯誤）、費率表載入／驗證／適用欄位／租車欄位、`lookup_price` |
| `profile.json` | `merge_patch` 36 筆、`missing_fields`／`validate_profile` 10 筆、`region_of` 22 筆、`requirements_for` 74 筆 |
| `recommend.json` | `build_recommendation` 13 組（每組前 N 名、多人租車假設、地區推測、調高保額、全部無法報價） |
| `narrate.json` | `extract_numbers`、`render_template`、`render_report`、`check_numbers`（通過與不通過） |

`pricing.json` 用緊湊格式，因為 pre-commit 的 `check-added-large-files` 上限是 500KB。

## 條款警示的假函式

推薦的條款警示在第 2 階段才接真的檢索。對照資料用下面的假函式產生，測試裡的假函式必須與它相同（`fake_warn`，在下方腳本內）：活動「滑雪」回 `exclusion_found` 並附一筆引用，「潛水」回 `not_stated`，其他活動沒有警示。

## 重新產生

```bash
S=<暫存目錄>   # 腳本放在 repo 外，不要放進原型
# 1. 把下面「產生腳本」存成 $S/gen_golden.py，「拆檔腳本」存成 $S/split_golden.py
# 2. 在原型執行（原型唯讀；結果只導向到 repo 外）
cd /mnt/c/project/insurance_agent && docker compose run --rm -T app python - < $S/gen_golden.py > $S/all.json
# 3. 拆成四個檔案
python3 -I $S/split_golden.py $S/all.json <本 repo>/backend/tests/golden
```

重新產生後用 `git diff` 看差異；原型的資料或邏輯有改，差異就會出現，要先和使用者確認再提交。

## 產生腳本（gen_golden.py，在原型容器內執行）

```python
"""在原型（insurance_agent）容器內執行，把第 1 階段範圍的函式對固定輸入的輸出印成一份 JSON 到 stdout。

用法（在原型目錄）：
    docker compose run --rm -T app python - < gen_golden.py > all.json
再用 split_golden.py 拆成 pricing.json、profile.json、recommend.json、narrate.json。
"""

import json
from dataclasses import asdict
from pathlib import Path

from insurance_agent.agent.clauses_check import Citation, ClauseWarning
from insurance_agent.agent.narrate import check_numbers, extract_numbers, render_report, render_template
from insurance_agent.agent.profile import (
    TripProfile,
    TripProfilePatch,
    merge_patch,
    missing_fields,
    validate_profile,
)
from insurance_agent.agent.recommend import build_recommendation
from insurance_agent.agent.regions import region_of
from insurance_agent.agent.requirements import requirements_for
from insurance_agent.ingest.cathay_rates import RATES_DIR
from insurance_agent.ingest.rates_schema import load_rate_table, lookup_price, validate_rate_table
from insurance_agent.pricing.quote import Requirement, Traveler, quote
from insurance_agent.pricing.tables import (
    eligible_columns,
    is_rental_car_column,
    load_main_tables,
    select_main_tables,
)


def err(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- pricing
main_tables = load_main_tables()
all_tables = {p.stem: load_rate_table(str(p)) for p in sorted(Path(RATES_DIR).glob("*.json"))}


def run_quote(days, travelers, req):
    try:
        plans, unavailable = quote(days, [Traveler(a, c) for a, c in travelers], Requirement(**req))
        return {"plans": [asdict(p) for p in plans], "unavailable": [asdict(u) for u in unavailable]}
    except Exception as e:  # noqa: BLE001
        return err(e)


quote_cases = []


def add_quote(label, days, travelers, req):
    quote_cases.append(
        {
            "id": f"q{len(quote_cases) + 1:03d}-{label}",
            "days": days,
            "travelers": [list(t) for t in travelers],
            "requirement": req,
            "expected": run_quote(days, travelers, req),
        }
    )


DEFAULT = {}
traveler_sets = {
    "solo30": [(30, False)],
    "adult-child": [(30, False), (8, False)],
    "three-car": [(30, True), (28, False), (5, False)],
    "four": [(40, True), (38, False), (10, False), (3, False)],
}
reqs = {
    "none": {},
    "ill300": {"illness_medical": 300_000},
    "ill500-acc300": {"illness_medical": 500_000, "accident_medical": 300_000},
    "ill1m-death1m": {"illness_medical": 1_000_000, "accident_medical": 500_000, "accident_death": 1_000_000},
    "ill2m": {"illness_medical": 2_000_000, "accident_medical": 1_000_000},
    "unmet-huge": {"illness_medical": 99_000_000},
    "infect-yes": {"illness_medical": 300_000, "infectious": True},
    "infect-no": {"illness_medical": 300_000, "infectious": False},
}
all_days = sorted({d for t in main_tables.values() for d in t.days})
missing_days = [d for d in range(1, 400) if d not in all_days][:4]
for days in (1, 3, 7, 30):
    for tname, trav in traveler_sets.items():
        for rname, req in reqs.items():
            add_quote(f"d{days}-{tname}-{rname}", days, trav, req)
for d in sorted(set([1, 2, 5, 10, 15, 29, 30, 31, 45, 60, 90, 180, 181, 365, 0, -1] + missing_days + all_days[-3:])):
    add_quote(f"days{d}", d, [(30, False)], {"illness_medical": 300_000})
bounds = set()
for t in main_tables.values():
    for c in t.columns:
        for edge in (c.age_min, c.age_max):
            if edge != 999:
                bounds.update([edge - 1, edge, edge + 1])
bounds.update([0, 1, 14, 15, 120, 121, -1])
for age in sorted(bounds):
    add_quote(f"age{age}", 5, [(age, False)], {"illness_medical": 300_000})
    add_quote(f"age{age}-car", 5, [(age, True)], {"illness_medical": 300_000})
add_quote("five-travelers", 5, [(30, False)] * 5, DEFAULT)
add_quote("zero-travelers", 5, [], DEFAULT)
add_quote("mixed-ages-bounds", 7, [(0, False), (15, True), (75, False), (80, False)], {"illness_medical": 500_000})

tables_info = {
    "all_table_ids": sorted(all_tables),
    "main_table_ids": sorted(select_main_tables(all_tables)),
    "validate": {tid: validate_rate_table(t) for tid, t in sorted(all_tables.items())},
    "rental_columns": {
        tid: [c.key for c in t.columns if is_rental_car_column(c)] for tid, t in sorted(all_tables.items())
    },
    "eligible": {
        tid: {str(a): [c.key for c in eligible_columns(t, a)] for a in sorted(bounds)}
        for tid, t in sorted(all_tables.items())
    },
}
lookups = []
for tid, t in sorted(main_tables.items()):
    for col in (t.columns[0].key, t.columns[-1].key, "no_such_col"):
        for day in sorted(set(t.days + [t.days[-1] + 1, 0])):
            try:
                result = {"price": lookup_price(t, col, day)}
            except Exception as e:  # noqa: BLE001
                result = err(e)
            lookups.append({"table_id": tid, "column": col, "days": day, "expected": result})
tables_info["lookups"] = lookups

# ---------------------------------------------------------------- profile
merge_cases = []


def add_merge(label, profile, patch):
    p, changes = merge_patch(TripProfile(**profile), TripProfilePatch(**patch))
    merge_cases.append(
        {
            "id": f"m{len(merge_cases) + 1:03d}-{label}",
            "profile": profile,
            "patch": patch,
            "expected": {"profile": p.model_dump(), "changes": changes},
        }
    )


add_merge("empty-patch", {}, {})
add_merge("fill-all", {}, {"destination": "日本", "days": 5, "ages": [30, 28], "travelers": 2,
                           "activities": ["滑雪"], "wants_infectious": True})
add_merge("none-keeps-known", {"destination": "日本", "days": 5, "ages": [30]}, {"destination": None, "days": None, "ages": None})
add_merge("blank-destination", {"destination": "日本"}, {"destination": "   "})
add_merge("strip-destination", {}, {"destination": "  泰國  "})
add_merge("days-zero", {"days": 5}, {"days": 0})
add_merge("days-negative", {}, {"days": -3})
add_merge("days-change", {"days": 5}, {"days": 7})
add_merge("days-same", {"days": 5}, {"days": 5})
add_merge("ages-invalid", {"ages": [30]}, {"ages": [30, 121]})
add_merge("ages-negative", {}, {"ages": [-1]})
add_merge("ages-empty-list", {"ages": [30]}, {"ages": []})
add_merge("ages-boundary", {}, {"ages": [0, 120]})
add_merge("travelers-zero", {"travelers": 2}, {"travelers": 0})
add_merge("travelers-ok", {}, {"travelers": 3})
add_merge("activities-alias", {}, {"activities": ["單板滑雪", "爬山", "自駕", "浮潛"]})
add_merge("activities-add-only", {"activities": ["滑雪"]}, {"activities": ["潛水", "滑雪"]})
add_merge("activities-no-first", {}, {"no_activities": True})
add_merge("activities-no-keeps-known", {"activities": ["滑雪"]}, {"no_activities": True})
add_merge("activities-no-keeps-empty", {"activities": []}, {"no_activities": True})
add_merge("activities-and-no", {}, {"activities": ["潛水"], "no_activities": True})
add_merge("infectious-yes", {}, {"wants_infectious": True})
add_merge("infectious-no", {"wants_infectious": True}, {"wants_infectious": False})
add_merge("infectious-unsure", {}, {"infectious_unsure": True})
add_merge("infectious-unsure-with-value", {}, {"infectious_unsure": True, "wants_infectious": True})
add_merge("infectious-unsure-after-known", {"wants_infectious": False}, {"infectious_unsure": True})
add_merge("infectious-decides-after-unsure", {"infectious_undecided": True}, {"wants_infectious": True})
add_merge("raise-once", {}, {"raise_coverage": True})
add_merge("raise-cap", {"coverage_steps": 3}, {"raise_coverage": True})
add_merge("raise-twice", {"coverage_steps": 1}, {"raise_coverage": True})
add_merge("explicit-wan", {}, {"illness_medical_wan": 300, "accident_medical_wan": 100, "accident_death_wan": 500})
add_merge("explicit-wan-zero", {}, {"illness_medical_wan": 0})
add_merge("explicit-wan-too-big", {}, {"accident_death_wan": 5001})
add_merge("explicit-wan-max", {}, {"illness_medical_wan": 5000})
add_merge("explicit-wan-negative", {}, {"accident_medical_wan": -5})
add_merge("explicit-overrides", {"min_illness_medical": 1_000_000}, {"illness_medical_wan": 200})

profile_checks = []
for label, prof in {
    "empty": {},
    "dest-only": {"destination": "日本"},
    "complete": {"destination": "日本", "days": 5, "ages": [30], "activities": [], "wants_infectious": True},
    "undecided": {"destination": "日本", "days": 5, "ages": [30], "activities": [], "infectious_undecided": True},
    "ages-vs-travelers-mismatch": {"destination": "日本", "days": 5, "ages": [30], "travelers": 2,
                                   "activities": [], "wants_infectious": False},
    "travelers-no-ages": {"destination": "日本", "days": 5, "travelers": 2, "activities": [], "wants_infectious": False},
    "empty-destination": {"destination": "", "days": 5, "ages": [30], "activities": [], "wants_infectious": False},
    "four": {"ages": [1, 2, 3, 4]},
    "five-ages": {"ages": [1, 2, 3, 4, 5]},
    "six-travelers": {"travelers": 6},
}.items():
    p = TripProfile(**prof)
    profile_checks.append(
        {"id": label, "profile": prof, "missing": missing_fields(p), "validate": validate_profile(p)}
    )

region_cases = []
for dest in ["日本", "日本北海道", "東京", "美國", "美國夏威夷", "法國巴黎", "德國", "英國", "泰國", "韓國首爾",
             "越南", "新加坡", "澳洲", "紐西蘭", "加拿大", "大洋洲", "大洋洲小島", "火星", "", "Japan", "香港", "中國上海"]:
    region, assumed = region_of(dest)
    region_cases.append({"destination": dest, "expected": [region, assumed]})

requirement_cases = []


def add_req(label, prof):
    req, reasons = requirements_for(TripProfile(**prof))
    requirement_cases.append(
        {"id": f"r{len(requirement_cases) + 1:03d}-{label}", "profile": prof,
         "expected": {"requirement": asdict(req), "reasons": reasons}}
    )


for region in (None, "japan_europe_us", "other"):
    for acts in (None, [], ["滑雪"], ["租車自駕"], ["潛水", "登山"], ["浮潛"]):
        for travelers in (None, 1, 2):
            add_req(f"{region}-{acts}-{travelers}", {"region": region, "activities": acts, "travelers": travelers})
for region in ("japan_europe_us", "other"):
    for steps in (0, 1, 2, 3, 4, 10):
        add_req(f"{region}-steps{steps}", {"region": region, "coverage_steps": steps, "activities": ["滑雪"]})
add_req("explicit-illness", {"region": "other", "min_illness_medical": 2_000_000})
add_req("explicit-accident", {"region": "other", "min_accident_medical": 1_500_000})
add_req("explicit-death", {"region": "other", "min_accident_death": 3_000_000})
add_req("explicit-all", {"region": "japan_europe_us", "min_illness_medical": 1_000_000,
                         "min_accident_medical": 500_000, "min_accident_death": 2_000_000})
add_req("steps-and-explicit", {"region": "other", "coverage_steps": 2, "min_illness_medical": 400_000})
for inf in (True, False):
    add_req(f"infectious-{inf}", {"region": "other", "wants_infectious": inf})
add_req("undecided", {"region": "other", "infectious_undecided": True})


# -------------------------------------------------------------- recommend
def fake_warn(profile, table_id):
    """條款警示的假函式（第 1 階段的對照與測試共用，定義要與 golden/README.md 一致）。"""
    out = []
    for a in profile.activities or []:
        if a == "滑雪":
            out.append(
                ClauseWarning(
                    a, "exclusion_found", f"{a}可能不在保障內",
                    [Citation("富邦", f"{table_id} 條款", 18, "除外責任", 12, "…滑雪…")],
                )
            )
        elif a == "潛水":
            out.append(ClauseWarning(a, "not_stated", f"{a}條款未載明", []))
    return out


recommend_inputs = {
    "japan-solo": ({"destination": "日本", "region": "japan_europe_us", "days": 5, "ages": [30], "travelers": 1,
                    "activities": [], "wants_infectious": True}, 3),
    "japan-solo-top1": ({"destination": "日本", "region": "japan_europe_us", "days": 5, "ages": [30], "travelers": 1,
                         "activities": [], "wants_infectious": False}, 1),
    "thai-undecided": ({"destination": "泰國", "region": "other", "days": 7, "ages": [35, 33], "travelers": 2,
                        "activities": ["潛水"], "infectious_undecided": True}, 3),
    "ski-family": ({"destination": "日本北海道", "region": "japan_europe_us", "days": 6, "ages": [40, 38, 10],
                    "travelers": 3, "activities": ["滑雪"], "wants_infectious": False}, 3),
    "car-two": ({"destination": "美國", "region": "japan_europe_us", "days": 10, "ages": [45, 44], "travelers": 2,
                 "activities": ["租車自駕"], "wants_infectious": True}, 3),
    "car-solo": ({"destination": "美國", "region": "japan_europe_us", "days": 10, "ages": [45], "travelers": 1,
                  "activities": ["租車自駕"], "wants_infectious": True}, 3),
    "region-assumed": ({"destination": "火星", "region": "japan_europe_us", "region_assumed": True, "days": 3,
                        "ages": [30], "travelers": 1, "activities": [], "wants_infectious": None}, 3),
    "raised": ({"destination": "日本", "region": "japan_europe_us", "days": 5, "ages": [30], "travelers": 1,
                "activities": [], "wants_infectious": True, "coverage_steps": 2}, 3),
    "explicit-big": ({"destination": "日本", "region": "japan_europe_us", "days": 5, "ages": [30], "travelers": 1,
                      "activities": [], "wants_infectious": True, "min_illness_medical": 5_000_000,
                      "min_accident_medical": 2_000_000, "min_accident_death": 3_000_000}, 3),
    "unmet": ({"destination": "日本", "region": "japan_europe_us", "days": 5, "ages": [30], "travelers": 1,
               "activities": [], "wants_infectious": True, "min_illness_medical": 90_000_000}, 3),
    "long-days": ({"destination": "日本", "region": "japan_europe_us", "days": 90, "ages": [30], "travelers": 1,
                   "activities": [], "wants_infectious": False}, 3),
    "no-table-days": ({"destination": "泰國", "region": "other", "days": 11, "ages": [30], "travelers": 1,
                       "activities": [], "wants_infectious": None}, 3),
    "senior-child": ({"destination": "泰國", "region": "other", "days": 5, "ages": [78, 8], "travelers": 2,
                      "activities": ["登山"], "wants_infectious": None}, 2),
}
recommend_cases = []
narrate_cases = []
for label, (prof, top_n) in recommend_inputs.items():
    rec = build_recommendation(TripProfile(**prof), top_n=top_n, warn_fn=fake_warn)
    recommend_cases.append(
        {
            "id": label,
            "profile": prof,
            "top_n": top_n,
            "expected": {
                "to_dict": rec.to_dict(),
                "numbers": sorted(rec.numbers(), key=int),
                "requirement": asdict(rec.requirement),
                "requirement_reasons": rec.requirement_reasons,
                "assumptions": rec.assumptions,
                "group_names": list(rec.groups),
            },
        }
    )
    template = render_template(rec)
    probes = [
        template,
        template + "\n另有 99999 元",
        "總保費 123 元，保額 5 萬",
        "U3 方案、g2_500 欄位、1,234 元",
        "共 1,000,000 元，第 1 名，3 位旅客",
    ]
    narrate_cases.append(
        {
            "recommend_case": label,
            "template": template,
            "report": render_report(rec, template),
            "report_custom_body": render_report(rec, "自訂本文"),
            "probes": [{"text": t, "check_numbers": check_numbers(t, rec)} for t in probes],
        }
    )

extract_cases = [
    {"text": t, "expected": sorted(extract_numbers(t), key=int)}
    for t in ["", "沒有數字", "50 萬", "50萬元", "1,234,567 元", "U3 與 g2_500", "T068 條款第 18 條", "3.5 倍", "1,17",
              "保額 300 萬、傷害醫療 100 萬，共 5 天", "0 元", "2026-10-29", "第 1、2 名"]
]

out = {
    "pricing": {"quote": quote_cases, "tables": tables_info},
    "profile": {
        "merge": merge_cases,
        "checks": profile_checks,
        "regions": region_cases,
        "requirements": requirement_cases,
    },
    "recommend": recommend_cases,
    "narrate": {"extract_numbers": extract_cases, "cases": narrate_cases},
}
print(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True))
```

## 拆檔腳本（split_golden.py）

```python
import json, sys
from pathlib import Path

src, out = Path(sys.argv[1]), Path(sys.argv[2])
data = json.loads(src.read_text(encoding="utf-8"))
for name, value in data.items():
    # pricing 很大，用緊湊格式避免超過 pre-commit 的 500KB 上限；其他保留縮排方便 diff
    text = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if name == "pricing"
        else json.dumps(value, ensure_ascii=False, sort_keys=True, indent=1)
    )
    (out / f"{name}.json").write_text(text + "\n", encoding="utf-8")
```

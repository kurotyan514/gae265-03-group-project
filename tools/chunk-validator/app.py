"""Chunk 品質驗證 Dashboard。啟動：uv run streamlit run app.py"""

import html
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from validator.baseline import TOOL_A, TOOL_B
from validator.config import load_registry, load_settings
from validator.fetch import fetch_rules, list_snapshots, load_snapshot, save_snapshot
from validator.models import CHECKS, STATUS_ZH, Status
from validator.pdfs import load_manifest
from validator.progress import progress_rows, progress_summary
from validator.report import load_run, summary_rows, to_csv, to_excel, to_html
from validator.review import (
    GOLD_CHOICES,
    REVIEW_CHOICES,
    agreement,
    gold_key,
    load_gold,
    save_gold,
    save_review,
)
from validator.runner import list_runs, make_context, run_snapshot
from validator.selftest import run_selftest, save_selftest, summarize
from validator.textutil import diff_for_display

st.set_page_config(page_title="Chunk 品質驗證", page_icon="✅", layout="wide")

ICON = {"PASS": "🟢", "FAIL": "🔴", "WARNING": "🟡", "NOT_VERIFIED": "⚪"}
PAGES = [
    "① 執行驗證",
    "📦 導入進度",
    "② 驗證總覽",
    "③ 問題清單",
    "④ PDF vs Chunk 對照",
    "⑤ 驗證器可信度",
    "⑥ 匯出報告",
]


def label(status: str) -> str:
    return f"{ICON[status]} {STATUS_ZH[Status(status)]}"


@st.cache_resource(show_spinner="讀取 PDF、建立標準答案…")
def context_for(snapshot_file: str):
    _, items = load_snapshot(Path(snapshot_file))
    return make_context(items)


@st.cache_data
def page_image(pdf_path: str, page_no: int) -> bytes:
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        return doc[page_no - 1].get_pixmap(dpi=110).tobytes("png")


# ── 側邊欄：選擇驗證結果 ──────────────────────────────
st.sidebar.title("✅ Chunk 品質驗證")
page = st.sidebar.radio("功能", PAGES)
if st.sidebar.toggle(
    "PDF 頁面圖片調暗",
    value=True,
    help="白底 PDF 圖片在夜間模式太刺眼時打開；只改顯示亮度，不影響判斷",
):
    st.markdown(
        "<style>[data-testid='stImage'] img{filter:brightness(.7)}</style>",
        unsafe_allow_html=True,
    )
runs = list_runs()
run_dir = None
if runs:
    run_dir = st.sidebar.selectbox("驗證結果", runs, format_func=lambda p: p.name)
    meta, findings, chunks = load_run(run_dir)
    snapshot_path = Path(__file__).parent / "data" / "snapshots" / meta["snapshot_file"]
    st.sidebar.caption(
        f"資料取得：{meta['snapshot'].get('fetched_at', '')}\n\n"
        f"規則版本：{meta['rules_version']}\n\n資料指紋：{meta['snapshot'].get('fingerprint', '')}"
    )


def need_run() -> bool:
    if run_dir is None:
        st.info("還沒有驗證結果，請先到「① 執行驗證」。")
        return False
    return True


# ── ① 執行驗證 ─────────────────────────────────────
if page == PAGES[0]:
    st.header("① 執行驗證")
    st.markdown(
        "流程：**抓取資料（存成快照）→ 執行驗證**。只對條文 API 發出讀取請求，不會修改任何資料。"
    )
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("1. 抓取最新資料")
        url = st.text_input("API 位址", load_settings().api_base_url)
        if st.button("抓取並存成快照", type="primary"):
            try:
                with st.spinner("讀取中…"):
                    items, extra = fetch_rules(url.rstrip("/"))
                st.success(
                    f"已存快照 {save_snapshot(items, extra, url.rstrip('/')).name}（{len(items)} 筆）"
                )
            except Exception as e:
                st.error(
                    f"抓取失敗：{e}。可能是 ngrok 網址換了或 後端服務暫停；仍可用既有快照驗證。"
                )
    with c2:
        st.subheader("2. 選擇快照並驗證")
        snaps = list_snapshots()
        if not snaps:
            st.warning("還沒有快照")
        else:
            snap = st.selectbox("快照", snaps, format_func=lambda p: p.name)
            snap_meta, _ = load_snapshot(snap)
            st.caption(
                f"{snap_meta.get('total')} 筆｜來源：{snap_meta.get('source')}｜指紋 {snap_meta.get('fingerprint')}"
            )
            if st.button("執行六項驗證", type="primary"):
                with st.spinner("驗證中（第一次會讀取全部 PDF，約 10 秒）…"):
                    new_run = run_snapshot(snap)
                st.success(f"完成：{new_run.name}。請到左側選擇這個驗證結果。")
                st.rerun()

    st.subheader("原始 PDF 與險種登記")
    manifest = load_manifest()
    reg = load_registry()
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "險種": c,
                    "公司": i.company,
                    "名稱": i.name,
                    "PDF": i.pdf_file,
                    "PDF 存在": "✅" if i.pdf_path.exists() else "❌",
                    "來源": manifest.get(c, {}).get("source", ""),
                    "官方版本確認": "✅" if i.pdf_sha256 else "未確認",
                }
                for c, i in reg.items()
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "新增險種或保險公司：編輯 config/insurances.csv，並把 PDF 放到 data/pdfs/<公司>/。"
    )

# ── 📦 導入進度 ────────────────────────────────────
elif page == PAGES[1] and need_run():
    st.header("📦 導入進度")
    st.markdown(
        "**應導入清單 = `config/insurances.csv` 登記表**。每個險種一列：導入了沒、導對了沒、下一步誰做什麼。"
    )
    rows = progress_rows(load_registry(), chunks, findings, meta)
    s = progress_summary(rows)
    cols = st.columns(4)
    cols[0].metric("應導入險種", s["應導入"])
    cols[1].metric("已導入", s["已導入"], help="登記表上的險種，API 的資料裡至少有一條")
    cols[2].metric("🟢 驗證完成", s["完成"], help="每一條六項都通過，而且沒有缺漏條文")
    cols[3].metric(
        "❓ 未登記", s["未登記"], help="API 有、登記表沒有（例如其他保險公司）"
    )
    if s["應導入"]:
        st.progress(s["已導入"] / s["應導入"], text=f"導入 {s['已導入']}/{s['應導入']}")
        st.progress(s["完成"] / s["應導入"], text=f"驗證完成 {s['完成']}/{s['應導入']}")

    df = pd.DataFrame(rows)
    stages = list(dict.fromkeys(df["進度"]))
    pick = st.multiselect("篩選進度", stages, default=stages)
    st.dataframe(
        df[df["進度"].isin(pick)].drop(columns="_stage"),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "進度判定（由上而下，符合就停）：❓ 不在登記表 → ⬜ API 沒有任何一條 → 📄 沒有 PDF 無法驗證 → "
        "🔴 有確定錯誤或缺條 → 🟡 有可疑或無法驗證的條文 → 🟢 全部通過。"
    )
    if "baseline_articles" not in meta:
        st.info(
            "這份驗證結果是舊版產生的，沒有「PDF 應有條數」。到①重新執行驗證即可補上。"
        )

# ── ② 驗證總覽 ─────────────────────────────────────
elif page == PAGES[2] and need_run():
    st.header("② 驗證總覽")
    overall = meta["chunk_overall"]
    cols = st.columns(5)
    cols[0].metric("Chunk 總數", meta["chunk_total"])
    for col, s in zip(
        cols[1:], ["PASS", "FAIL", "WARNING", "NOT_VERIFIED"], strict=True
    ):
        col.metric(label(s), overall.get(s, 0))
    st.caption(
        "每條條文的「整體」取六項中最嚴重的狀態。🔴 確定錯誤　🟡 可疑，需人工看圖　⚪ 缺資料無法驗證（不算通過）"
    )

    st.subheader("各險種 × 六項驗證")
    check_cols = list(CHECKS.values())

    def cell(series: pd.Series) -> str:
        counts = series.value_counts()
        parts = [
            f"{ICON[s]}{counts[s]}"
            for s in ("FAIL", "WARNING", "NOT_VERIFIED")
            if s in counts
        ]
        return " ".join(parts) or "🟢"

    table = (
        chunks.groupby("險種")
        .agg({**dict.fromkeys(check_cols, cell), "條號": "count"})
        .rename(columns={"條號": "條數"})
    )
    st.dataframe(table, use_container_width=True)

    c1, c2 = st.columns(2)
    issues = findings[findings["status"].isin(["FAIL", "WARNING"])]
    with c1:
        st.subheader("問題類型統計")
        if issues.empty:
            st.success("沒有 FAIL 或 WARNING")
        else:
            counts = (
                issues.groupby(["驗證項目", "rule", "狀態"])
                .size()
                .reset_index(name="筆數")
            )
            st.dataframe(
                counts.sort_values("筆數", ascending=False),
                hide_index=True,
                use_container_width=True,
            )
    with c2:
        st.subheader("整份資料無法驗證的項目")
        nv = findings[
            (findings["status"] == "NOT_VERIFIED") & (findings["scope"] != "chunk")
        ]
        for _, r in (
            nv.groupby(["rule", "message"]).size().reset_index(name="n").iterrows()
        ):
            st.markdown(
                f"- ⚪ {r['message']}" + (f"（{r['n']} 個險種）" if r["n"] > 1 else "")
            )
        st.caption("這些不是錯誤，而是缺少資料；補齊後會自動改成可驗證。")

# ── ③ 問題清單 ─────────────────────────────────────
elif page == PAGES[3] and need_run():
    st.header("③ 問題清單")
    data = findings[findings["status"] != "PASS"].copy()
    f1, f2, f3, f4, f5 = st.columns(5)
    pick_code = f1.multiselect(
        "險種", sorted(c for c in data["insurance_code"].unique() if c)
    )
    pick_check = f2.multiselect("驗證項目", list(CHECKS.values()))
    pick_status = f3.multiselect(
        "狀態",
        ["FAIL", "WARNING", "NOT_VERIFIED"],
        default=["FAIL", "WARNING"],
        format_func=label,
    )
    pick_sev = f4.multiselect("嚴重度", ["高", "中", "低", "—"])
    pick_review = f5.multiselect("人工覆核", REVIEW_CHOICES)
    for col, picked in [
        ("insurance_code", pick_code),
        ("驗證項目", pick_check),
        ("status", pick_status),
        ("severity", pick_sev),
        ("人工覆核", pick_review),
    ]:
        if picked:
            data = data[data[col].isin(picked)]
    view = data.assign(狀態=data["status"].map(label))[
        [
            "狀態",
            "severity",
            "驗證項目",
            "insurance_code",
            "article_no",
            "message",
            "人工覆核",
        ]
    ].rename(
        columns={
            "severity": "嚴重度",
            "insurance_code": "險種",
            "article_no": "條號",
            "message": "說明",
        }
    )
    st.caption(f"共 {len(view)} 筆。點選一列看詳細資訊與填寫人工覆核。")
    event = st.dataframe(
        view,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="issues",
    )
    if event.selection.rows:
        row = data.iloc[event.selection.rows[0]]
        st.divider()
        st.subheader(
            f"{label(row['status'])}　{row['insurance_code']} 第 {row['article_no']} 條　{row['驗證項目']}"
        )
        st.markdown(f"**說明**：{row['message']}")
        if row["suggestion"]:
            st.markdown(f"**建議處理**：{row['suggestion']}")
        st.markdown(f"**規則代碼**：`{row['rule']}`　**範圍**：{row['scope']}")
        if row["evidence"]:
            with st.expander("證據"):
                st.json(json.loads(row["evidence"]))
        if pd.notna(row["article_no"]):
            st.info(
                "到「④ PDF vs Chunk 對照」選同一個險種與條號，可看原文、差異與 PDF 頁面圖片。"
            )
        with st.form("review"):
            st.markdown("**人工覆核**")
            current = (
                REVIEW_CHOICES.index(row["人工覆核"])
                if row["人工覆核"] in REVIEW_CHOICES
                else 0
            )
            decision = st.selectbox("判斷", REVIEW_CHOICES, index=current)
            note = st.text_area(
                "備註（例如：看了 PDF 第 3 頁圖片，確認公式屬於第 27 條）",
                row["覆核備註"] or "",
            )
            reviewer = st.text_input("覆核人", "Lala")
            if st.form_submit_button("儲存覆核"):
                save_review(row["key"], decision, note, reviewer)
                st.success("已儲存")
                st.rerun()

# ── ④ PDF vs Chunk 對照 ─────────────────────────────
elif page == PAGES[4] and need_run():
    st.header("④ PDF vs Chunk 對照")
    ctx = context_for(str(snapshot_path))
    codes = sorted(ctx.by_code)
    c1, c2 = st.columns(2)
    code = c1.selectbox(
        "險種",
        codes,
        format_func=lambda c: (
            f"{c} {ctx.registry[c].name if c in ctx.registry else '（未登記）'}"
        ),
    )
    rows = ctx.by_code[code]
    no = c2.selectbox(
        "條號",
        [r["article_no"] for r in rows],
        format_func=lambda n: (
            f"第 {n} 條 "
            + next(r["title"] for r in rows if r["article_no"] == n)
            + " "
            + ICON[
                chunks[(chunks["險種"] == code) & (chunks["條號"] == n)]["整體"].iloc[0]
            ]
        ),
    )
    item = next(r for r in rows if r["article_no"] == no)
    bl = ctx.baselines.get(code)
    art = bl.articles.get(no) if bl else None

    mine = findings[
        (findings["insurance_code"] == code)
        & (findings["article_no"] == no)
        & (findings["status"] != "PASS")
    ]
    for _, f in mine.iterrows():
        st.markdown(f"{label(f['status'])}　**{f['驗證項目']}**：{f['message']}")
    if mine.empty:
        st.success("這一條六項驗證都通過")

    if art is None:
        st.warning("PDF 標準答案中沒有這一條（或沒有 PDF），無法對照。")
    else:
        tool = st.radio(
            "PDF 文字來源",
            [TOOL_A, TOOL_B],
            horizontal=True,
            help="兩套工具各自讀 PDF。兩者一致時才當作確定的標準答案。",
        )
        src = art.a if tool == TOOL_A else art.b
        if not art.agreed:
            st.warning(
                "⚠️ 兩套工具對這一條的讀法不同："
                + "；".join(art.disagreements)
                + "。請以下方 PDF 頁面圖片為準。"
            )
        if src is None:
            st.info(f"{tool} 沒有讀到這一條")
        else:
            left, right = [], []
            for kind, e, a in diff_for_display(src.text, item["content"]):
                e, a = html.escape(e), html.escape(a)
                if kind == "equal":
                    left.append(e)
                    right.append(a)
                else:
                    if e:
                        left.append(f'<mark style="background:#ffc9c9">{e}</mark>')
                    if a:
                        right.append(f'<mark style="background:#b2f2bb">{a}</mark>')
            box = "border:1px solid #ddd;border-radius:6px;padding:12px;line-height:1.9;max-height:420px;overflow:auto"
            pdf_col, chunk_col = st.columns(2)
            pdf_col.markdown(
                f"**PDF 原文**（{tool}，p{src.page_start}-{src.page_end}）　標題：{html.escape(src.title)}"
            )
            pdf_col.markdown(
                f'<div style="{box}">{"".join(left)}</div>', unsafe_allow_html=True
            )
            chunk_col.markdown(
                f"**API 的 Chunk**（p{item['page_start']}-{item['page_end']}）　標題：{html.escape(item['title'])}"
            )
            chunk_col.markdown(
                f'<div style="{box}">{"".join(right)}</div>', unsafe_allow_html=True
            )
            st.caption(
                "已去掉空白與換行再比對（只剩格式差異會視為相同）。🟥 PDF 有、Chunk 沒有　🟩 Chunk 有、PDF 沒有"
            )
            with st.expander("未正規化的原始文字"):
                a1, a2 = st.columns(2)
                a1.text(src.text)
                a2.text(item["content"])

    if bl:
        pages = sorted(
            {item["page_start"], item["page_end"]}
            | ({art.best.page_start, art.best.page_end} if art else set())
        )
        pages = [
            p for p in range(min(pages), max(pages) + 1) if 1 <= p <= bl.page_count
        ]
        st.subheader("PDF 頁面圖片（最終依據）")
        for col, p in zip(st.columns(len(pages)), pages, strict=True):
            col.image(
                page_image(str(bl.pdf_path), p),
                caption=f"第 {p} 頁",
                use_container_width=True,
            )

        st.subheader("人工標準答案")
        st.caption(
            "看完上方頁面圖片後，判斷 API 的這一條是否正確。這是用來量測驗證器精確度的依據（見⑤）。"
        )
        fp = meta["snapshot"].get("fingerprint", "")
        key = gold_key(code, no, fp)
        old = load_gold().get(key, {})
        with st.form("gold"):
            verdict = st.radio(
                "判斷",
                GOLD_CHOICES,
                index=GOLD_CHOICES.index(old.get("verdict", "未標註")),
                horizontal=True,
            )
            note = st.text_input("備註", old.get("note", ""))
            reviewer = st.text_input("標註人", old.get("reviewer", "Lala"))
            if st.form_submit_button("儲存"):
                save_gold(key, verdict, note, reviewer)
                st.success("已儲存")

# ── ⑤ 驗證器可信度 ─────────────────────────────────
elif page == PAGES[5] and need_run():
    st.header("⑤ 驗證器可信度")
    st.markdown(
        "驗證器本身也要被驗證。這裡用兩種方式量測：**故意埋錯**（測漏抓）與**人工標準答案**（測誤報與漏抓）。"
    )

    st.subheader("A. 故意埋錯測試")
    st.caption(
        "從目前完全通過的條文中挑目標，在資料副本裡做壞一個地方，看驗證器能否以 FAIL 抓到。原始資料不會被修改。"
    )
    reps = st.slider("每種錯誤測幾次", 1, 10, 5)
    if st.button("執行埋錯測試", type="primary"):
        with st.spinner("測試中…"):
            rows = run_selftest(context_for(str(snapshot_path)), reps=reps)
            st.session_state["selftest"] = rows
            save_selftest(rows)
    if rows := st.session_state.get("selftest"):
        s = summarize(rows)
        cols = st.columns(5)
        for col, k in zip(
            cols, ["埋錯數", "抓到", "只給警告", "漏抓", "偵錯率"], strict=True
        ):
            col.metric(k, s[k])
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    st.subheader("B. 人工標準答案比對")
    fp = meta["snapshot"].get("fingerprint", "")
    table = agreement(chunks.to_dict("records"), load_gold(), fp)
    n = table.pop("已標註條數")
    if n == 0:
        st.info(
            "還沒有人工標註。到「④ PDF vs Chunk 對照」看頁面圖片後標註「人工確認：正確／有誤」。建議每個險種至少 3 條，加上所有 🟡 警告。"
        )
    else:
        cols = st.columns(len(table))
        for col, (k, v) in zip(cols, table.items(), strict=True):
            col.metric(k, v)
        wrong = table["誤報"] + table["漏抓"]
        st.markdown(f"已標註 **{n}** 條；驗證器與人工判斷不一致 **{wrong}** 條。")
        if wrong == 0:
            st.success(
                f"可以這樣說：「人工抽查 {n} 條，驗證器判定全部與人工一致；推估錯判率上限約 {3 / n:.0%}（95% 信心）。」"
            )
        else:
            st.warning("有不一致的條文：請檢查驗證規則或人工判斷，修正後再重跑。")

# ── ⑥ 匯出報告 ─────────────────────────────────────
elif page == PAGES[6] and need_run():
    st.header("⑥ 匯出驗收報告")
    st.table(
        pd.DataFrame(summary_rows(meta), columns=["項目", "內容"]).set_index("項目")
    )
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "下載 CSV（問題清單）",
        to_csv(findings),
        f"chunk驗收_{meta['run_id']}.csv",
        "text/csv",
    )
    c2.download_button(
        "下載 Excel（完整報告）",
        to_excel(meta, findings, chunks),
        f"chunk驗收_{meta['run_id']}.xlsx",
    )
    c3.download_button(
        "下載 HTML（可直接分享）",
        to_html(meta, findings, chunks),
        f"chunk驗收_{meta['run_id']}.html",
        "text/html",
    )
    st.caption("報告中的「人工覆核」欄會帶入目前的覆核紀錄；未覆核的項目僅為機器判定。")

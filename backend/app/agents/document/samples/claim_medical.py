"""泰國醫療 demo 的理賠申請書（D10）：安達產物「保險金申請書」第 1 頁，手寫填上急性腸胃炎門診的假資料。

空白表單 chubb_claim_form_blank.pdf 取自安達產物官網「表單下載」的 Form004
（健康與傷害險保險金申請書／旅行綜合保險金申請書）第 1 頁。
由 make_samples.py 產生：
    cd backend && uv run python -m app.agents.document.samples.make_samples --medical
"""

import io
import random
from functools import cache
from pathlib import Path

import pymupdf
from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).parent
CHUBB_BLANK_FORM = HERE / "chubb_claim_form_blank.pdf"


@cache
def _hand_font() -> bytes:
    """手寫字型，裁成 make_samples.py 與這支程式出現過的字。

    make_samples 的 font() 只認 make_samples.py 裡的字，這裡的「曼谷、腸胃炎」等字不在裡面，所以另外裁。
    make_samples 在函式內才匯入：make_samples 也會匯入這支程式，放在最上面會循環匯入。
    """
    from app.agents.document.samples import make_samples as ms

    used = (
        set(Path(ms.__file__).read_text())
        | set(Path(__file__).read_text())
        | {chr(c) for c in range(0x20, 0x7F)}
    )
    tt = TTFont(str(ms.FONT_HAND), fontNumber=0)
    sub = subset.Subsetter(subset.Options())
    sub.populate(text="".join(used))
    sub.subset(tt)
    if "CFF " in tt:
        ms._cff_to_truetype(tt)
    out = io.BytesIO()
    tt.save(out)
    return out.getvalue()


def chubb_claim_form(doc: pymupdf.Document) -> None:
    """安達「保險金申請書」第 1 頁：陳怡君 2026-07-08 在曼谷急性腸胃炎看門診（與診斷書、收據一致）。

    表單沒有申請金額與匯款帳號欄（匯款要另附存摺影本），所以金額寫在事故經過裡，帳號不填。
    """
    from app.agents.document.samples.make_samples import (
        FONT_LIGHT,
        FOOTER,
        GRAY,
        INK,
        font,
    )

    blank = pymupdf.open(CHUBB_BLANK_FORM)
    doc.insert_pdf(blank, from_page=0, to_page=0)
    page = doc[-1]
    page.insert_font(fontname="H", fontbuffer=_hand_font())
    rnd = random.Random(708)

    def hand(x: float, y: float, s: str, size: float = 10.5) -> None:
        # 手寫：每段字的位置、大小、傾斜都有一點不同
        tilt = pymupdf.Matrix(rnd.uniform(-1.8, 1.8))
        at = pymupdf.Point(x + rnd.uniform(-0.8, 0.8), y + rnd.uniform(-0.8, 0.8))
        page.insert_text(
            at,
            s,
            fontname="H",
            fontsize=size + rnd.uniform(-0.4, 0.6),
            color=INK,
            morph=(at, tilt),
        )

    def tick(box_x: float, box_y: float) -> None:
        # 打勾：□ 字的左上角座標
        p0 = pymupdf.Point(box_x + 1.5, box_y + 7)
        p1 = pymupdf.Point(box_x + 4.5, box_y + 11)
        p2 = pymupdf.Point(box_x + 11, box_y)
        page.draw_polyline([p0, p1, p2], color=INK, width=1.3)

    tick(83.4, 70.1)  # 申請項目：個人保險
    tick(94.5, 98.8)  # 旅行平安險醫療
    hand(392, 108, "（海外突發疾病 門診）", 9)
    hand(346, 125, "陳怡君", 11)  # 要保人
    hand(98, 142, "陳怡君", 12)  # 被保險人
    hand(284, 142, "A223456789", 10.5)  # 身份證字號
    for x, v in ((452, "81"), (499, "3"), (533, "14")):
        hand(x, 142, v)  # 出生日期：民國 81 年 3 月 14 日（1992-03-14）
    hand(170, 159, "行政人員 / 內勤 / 台北", 9.5)  # 目前職業/工作內容/地點
    tick(411, 150.1)  # 與要保人關係：本人
    hand(98, 176, "台北市大安區復興南路一段 100 號 5 樓", 10)  # 連絡地址
    hand(98, 193.5, "yichun.chen@example.com", 9.5)  # E-mail
    hand(487, 193.5, "0912-000-000", 9.5)  # 連絡電話（手機）
    hand(150, 227, "無", 10)  # 投保其他保險公司名稱
    for x, v in ((86, "115"), (129, "7"), (162, "8"), (200, "上"), (230, "10")):
        hand(x, 244, v)  # 事故時間：年月日 午 時
    hand(330, 244, "泰國曼谷", 10.5)  # 事故地點
    hand(
        38,
        277,
        "在曼谷用餐後腹瀉嘔吐，至診所門診，診斷急性腸胃炎。醫療費用 THB 1,450。",
        10,
    )  # 事故發生經過
    tick(165.1, 303.1)  # 給付方式：匯款
    tick(57.1, 468.1)  # 同意查詢聲明書：被保險人之本人
    hand(232, 531, "陳怡君", 14)  # 被保險人/受益人/立同意書人簽章
    hand(447, 531, "A223456789", 10.5)  # 身份證號碼
    for x, v in ((142, "115"), (207, "7"), (258, "15")):
        hand(x, 581, v)  # 申請日期：中華民國年月日
    page.insert_font(fontname="L", fontbuffer=font(FONT_LIGHT))
    page.insert_text((24, 836), FOOTER, fontname="L", fontsize=6, color=GRAY)

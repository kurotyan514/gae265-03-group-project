"""產生 /dev 文件辨識測試台的範例文件（只在開發者的 Mac 上跑，產出的 PDF 一起 commit）。

    cd backend && uv run python -m app.agents.document.samples.make_samples

版面參考真實的航空公司文件與電子機票收據，資料全部是虛構的：旅客「陳怡君」、
航空公司「福爾摩沙天空航空」都不存在，每頁底部都印「測試範例（資料虛構）」。
理賠申請書用富邦產險正式的「個人保險理賠申請書」（fubon_claim_form_blank.pdf，第 1 頁），
用手寫風格字型填上假資料。字型用 macOS 內建的黑體與翩翩體，所以要在 Mac 上產生；
backend 容器只讀產出的 PDF，不需要這些字型。
照片版（photo_*.jpg）由 PDF 轉圖再加上斜拍、陰影、反光、模糊，送 Azure 讀字。
"""

import io
import logging
import random
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf
from fontTools import subset
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

HERE = Path(__file__).parent
BLANK_FORM = HERE / "fubon_claim_form_blank.pdf"

FONT_LIGHT = "/System/Library/Fonts/STHeiti Light.ttc"
FONT_BOLD = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_HAND = next(
    Path("/System/Library/AssetsV2").glob("**/Hanzipen.ttc"),
    Path("Hanzipen.ttc"),
)


def _cff_to_truetype(tt: TTFont) -> None:
    """CFF 外框轉成 TrueType（fontTools 的 otf2ttf 範例）：pymupdf 對 CFF 字型的字位編號處理不對。"""
    # fontTools 的資料表沒有型別資訊，用 Any
    glyph_set: Any = tt.getGlyphSet()
    glyf: Any = newTable("glyf")
    glyf.glyphOrder = tt.getGlyphOrder()
    glyf.glyphs = {}
    for name in glyf.glyphOrder:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err=1.0, reverse_direction=True))
        glyf.glyphs[name] = pen.glyph()
    tt["loca"] = newTable("loca")
    tt["glyf"] = glyf
    del tt["CFF "]
    if "VORG" in tt:
        del tt["VORG"]
    maxp: Any = newTable("maxp")
    tt["maxp"] = maxp
    maxp.tableVersion = 0x00010000
    for k in (
        "maxZones maxTwilightPoints maxStorage maxFunctionDefs maxInstructionDefs "
        "maxStackElements maxSizeOfInstructions maxComponentElements"
    ).split():
        setattr(maxp, k, 0)
    maxp.maxZones = 1
    post: Any = tt["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    head: Any = tt["head"]
    head.glyphDataFormat = 0
    tt.sfntVersion = "\x00\x01\x00\x00"


@cache
def font(path: str | Path) -> bytes:
    """先裁成這支程式裡出現過的字（印出的字全寫在這裡），PDF 才不會超過 500 KB。

    存檔前再用 subset_fonts 裁成每份實際用到的字。手寫字型是 CFF，pymupdf 裁 CFF 會留下
    3 萬多個空字位、裁過再嵌入又會印成亂碼，所以先轉成 TrueType。
    """
    used = set(Path(__file__).read_text()) | {chr(c) for c in range(0x20, 0x7F)}
    tt = TTFont(str(path), fontNumber=0)
    sub = subset.Subsetter(subset.Options())
    sub.populate(text="".join(used))
    sub.subset(tt)
    if "CFF " in tt:
        _cff_to_truetype(tt)
    out = io.BytesIO()
    tt.save(out)
    return out.getvalue()


NAVY = (0.07, 0.18, 0.38)
GRAY = (0.45, 0.45, 0.45)
LINE = (0.75, 0.75, 0.75)
RED = (0.78, 0.12, 0.12)
INK = (0.09, 0.13, 0.46)  # 原子筆的藍

AIRLINE = "福爾摩沙天空航空"
AIRLINE_EN = "FORMOSA SKY AIRWAYS"
FOOTER = "測試範例（資料虛構）　SAMPLE ONLY — NOT A REAL DOCUMENT"


class Sheet:
    """一頁文件。字一律用整行寫入（「標籤：值」不拆開），去識別化才認得到標籤。"""

    def __init__(self, doc: pymupdf.Document, width: float = 595, height: float = 842):
        self.page = doc.new_page(width=width, height=height)
        self.page.insert_font(fontname="L", fontbuffer=font(FONT_LIGHT))
        self.page.insert_font(fontname="B", fontbuffer=font(FONT_BOLD))

    def text(
        self,
        x: float,
        y: float,
        s: str,
        size: float = 10,
        bold: bool = False,
        color: tuple[float, float, float] = (0, 0, 0),
    ) -> None:
        self.page.insert_text(
            (x, y), s, fontname="B" if bold else "L", fontsize=size, color=color
        )

    def box(
        self,
        r: tuple[float, float, float, float],
        fill: tuple[float, float, float] | None = None,
        color: tuple[float, float, float] | None = LINE,
        width: float = 0.7,
    ) -> None:
        self.page.draw_rect(pymupdf.Rect(r), color=color, fill=fill, width=width)

    def line(
        self, x0: float, y0: float, x1: float, y1: float, width: float = 0.6
    ) -> None:
        self.page.draw_line((x0, y0), (x1, y1), color=LINE, width=width)

    def logo(self, x: float, y: float, r: float = 13) -> None:
        """虛構航空公司的標誌：圓形裡一道斜線。"""
        self.page.draw_circle((x, y), r, color=(1, 1, 1), fill=NAVY, width=1.2)
        self.page.draw_line(
            (x - r * 0.6, y + r * 0.4),
            (x + r * 0.6, y - r * 0.5),
            color=(1, 1, 1),
            width=2,
        )

    def stamp(self, x: float, y: float, top: str, mid: str, bottom: str) -> None:
        """紅色圓形章（虛構單位）。"""
        self.page.draw_circle((x, y), 34, color=RED, width=1.6)
        self.page.draw_circle((x, y), 30, color=RED, width=0.6)
        for s, dy, size in ((top, -10, 7.5), (mid, 4, 9), (bottom, 16, 7)):
            w = (
                pymupdf.get_text_length(s, fontname="helv", fontsize=size)
                if s.isascii()
                else len(s) * size
            )
            self.page.insert_text(
                (x - w / 2, y + dy), s, fontname="B", fontsize=size, color=RED
            )

    def barcode(self, x: float, y: float, w: float, h: float, seed: int) -> None:
        rnd = random.Random(seed)
        cx = x
        while cx < x + w:
            bar = rnd.choice((0.8, 1.2, 1.8, 2.6))
            if rnd.random() > 0.35:
                self.page.draw_rect(
                    pymupdf.Rect(cx, y, cx + bar, y + h), color=None, fill=(0, 0, 0)
                )
            cx += bar + rnd.choice((0.8, 1.2, 1.6))

    def footer(self) -> None:
        h = self.page.rect.height
        self.text(24, h - 12, FOOTER, size=6.5, color=GRAY)


def airline_header(s: Sheet, title: str, title_en: str) -> None:
    s.box((0, 0, 595, 70), fill=NAVY, color=None)
    s.logo(48, 35)
    s.text(70, 32, AIRLINE, size=15, bold=True, color=(1, 1, 1))
    s.text(70, 48, AIRLINE_EN, size=8.5, color=(0.85, 0.9, 1))
    s.text(380, 32, title, size=15, bold=True, color=(1, 1, 1))
    s.text(380, 48, title_en, size=8.5, color=(0.85, 0.9, 1))


def rows(
    s: Sheet,
    x: float,
    y: float,
    items: list[tuple[str, str]],
    w: float = 515,
    h: float = 26,
) -> float:
    """表格：左邊英文欄名（小字），右邊「中文欄名：值」。"""
    for en, zh_value in items:
        s.box((x, y, x + w, y + h))
        s.box((x, y, x + 150, y + h), fill=(0.95, 0.96, 0.98))
        s.text(x + 6, y + 16, en, size=7.5, color=GRAY)
        s.text(x + 158, y + 17, zh_value, size=10.5)
        y += h
    return y


def delay_certificate(doc: pymupdf.Document, with_times: bool) -> None:
    s = Sheet(doc)
    airline_header(s, "班機延誤證明書", "FLIGHT DELAY CERTIFICATE")
    s.text(
        40, 100, "證明編號 Certificate No.：NRT-DLY-20260710-0412", size=9, color=GRAY
    )
    s.text(40, 128, "茲證明下列旅客搭乘本公司班機，因故延誤起飛，特此證明。", size=11)
    s.text(
        40,
        144,
        "This is to certify that the passenger below was on the following flight, which was delayed.",
        size=8.5,
        color=GRAY,
    )
    items = [
        ("Passenger Name", "旅客姓名：陳怡君　CHEN/YICHUN MS"),
        ("Booking Reference", "訂位代號：K7Q2MD"),
        ("Flight No.", "班機號碼：ZZ 198"),
        ("Flight Date", "班機日期：2026-07-10"),
        ("Sector", "航段：東京成田 NRT → 台北桃園 TPE"),
    ]
    if with_times:
        items += [
            ("Scheduled Departure (STD)", "原定起飛時間：10:30（當地時間）"),
            ("Actual Departure (ATD)", "實際起飛時間：16:45（當地時間）"),
            ("Length of Delay", "延誤時間：6 小時 15 分"),
        ]
    else:
        items += [("Length of Delay", "延誤時間：約 6 小時")]
    items += [
        ("Reason", "延誤原因：天候不佳（成田機場強風）Adverse weather"),
        ("Issued at", "開立單位：成田機場站 NRT Airport Station"),
        ("Date of Issue", "開立日期：2026-07-10"),
    ]
    y = rows(s, 40, 166, items)
    s.text(
        40,
        y + 30,
        "註：本證明僅證明班機延誤事實，供旅客向保險公司申請理賠使用。",
        size=9,
        color=GRAY,
    )
    s.text(
        40,
        y + 44,
        "Note: This certificate is issued for insurance claim purposes only.",
        size=8,
        color=GRAY,
    )
    s.text(330, y + 92, "站務主管 Duty Manager：", size=10)
    s.page.insert_font(fontname="H", fontbuffer=font(FONT_HAND))
    s.page.insert_text((450, y + 92), "林志明", fontname="H", fontsize=15, color=INK)
    s.stamp(500, y + 140, AIRLINE_EN[:6], "成田站", "2026.07.10")
    s.footer()


def boarding_pass(doc: pymupdf.Document) -> None:
    s = Sheet(doc, 595, 250)
    s.box((10, 10, 585, 240), color=NAVY, width=1.2)
    s.box((10, 10, 585, 48), fill=NAVY, color=None)
    s.logo(34, 29, 11)
    s.text(52, 34, f"{AIRLINE}  {AIRLINE_EN}", size=11, bold=True, color=(1, 1, 1))
    s.text(430, 34, "BOARDING PASS 登機證", size=11, bold=True, color=(1, 1, 1))
    s.page.draw_line((430, 48), (430, 240), color=LINE, width=0.8, dashes="[3 3] 0")
    s.text(24, 70, "姓名：CHEN/YICHUN MS", size=12, bold=True)
    s.text(24, 96, "FROM 出發", size=7, color=GRAY)
    s.text(24, 116, "東京成田 NRT", size=16, bold=True)
    s.text(200, 96, "TO 抵達", size=7, color=GRAY)
    s.text(200, 116, "台北桃園 TPE", size=16, bold=True)
    for i, (k, v) in enumerate(
        [
            ("FLIGHT 班機", "ZZ198"),
            ("DATE 日期", "10JUL"),
            ("BOARDING 登機時間", "10:00"),
            ("GATE 登機門", "21"),
            ("SEAT 座位", "32A"),
        ]
    ):
        x = 24 + i * 80
        s.text(x, 142, k, size=6.5, color=GRAY)
        s.text(x, 160, v, size=13, bold=True)
    s.text(24, 186, "CLASS 艙等：Y　SEQ：087　ETKT 999 2100000000", size=8, color=GRAY)
    s.text(
        24,
        200,
        "登機門於起飛前 20 分鐘關閉 Gate closes 20 minutes before departure",
        size=7,
        color=GRAY,
    )
    s.barcode(24, 206, 220, 26, seed=198)
    s.text(442, 70, "CHEN/YICHUN MS", size=9, bold=True)
    s.text(442, 92, "NRT → TPE", size=12, bold=True)
    s.text(442, 112, "ZZ198　10JUL", size=10)
    s.text(442, 130, "SEAT 32A　GATE 21", size=10)
    s.text(442, 148, "SEQ 087", size=9, color=GRAY)
    s.barcode(442, 160, 130, 40, seed=87)
    s.text(24, 247, FOOTER, size=6, color=GRAY)


def e_ticket(doc: pymupdf.Document) -> None:
    s = Sheet(doc)
    airline_header(s, "電子機票行程表暨收據", "E-TICKET ITINERARY RECEIPT")
    y = rows(
        s,
        40,
        92,
        [
            ("Passenger", "旅客姓名：陳怡君　CHEN/YICHUN MS"),
            ("Ticket Number", "機票號碼：999-2100000000"),
            ("Booking Reference", "訂位代號：K7Q2MD"),
            ("Issued by / Date", "開票單位：台北營業處　開票日期：2026-05-20"),
            ("Frequent Flyer", "會員號碼：FS 1234 5678"),
        ],
    )
    y += 26
    s.text(40, y, "行程 Itinerary", size=12, bold=True, color=NAVY)
    y += 10
    head = [
        "班機 Flight",
        "日期 Date",
        "出發 From",
        "抵達 To",
        "起飛 Dep",
        "抵達 Arr",
        "艙等 Class",
        "行李 Bag",
    ]
    xs = [40, 100, 170, 260, 350, 405, 460, 515]
    s.box((40, y, 555, y + 22), fill=(0.93, 0.95, 0.98))
    for x, h in zip(xs, head, strict=True):
        s.text(x + 4, y + 14, h, size=7.5, bold=True)
    y += 22
    for flight in (
        [
            "ZZ197",
            "2026-07-05",
            "台北 TPE",
            "東京 NRT",
            "08:30",
            "12:45",
            "Y 經濟",
            "23KG",
        ],
        [
            "ZZ198",
            "2026-07-10",
            "東京 NRT",
            "台北 TPE",
            "10:30",
            "13:30",
            "Y 經濟",
            "23KG",
        ],
    ):
        s.box((40, y, 555, y + 24))
        for x, v in zip(xs, flight, strict=True):
            s.text(x + 4, y + 16, v, size=9)
        y += 24
    y += 30
    s.text(40, y, "票價明細 Fare Details", size=12, bold=True, color=NAVY)
    y = rows(
        s,
        40,
        y + 10,
        [
            ("Fare", "票價：TWD 15,800"),
            ("Taxes / Fees", "稅金與燃油附加費：TWD 2,350"),
            ("Total", "合計：TWD 18,150"),
            ("Form of Payment", "付款方式：信用卡 VI XXXX XXXX XXXX 4821"),
        ],
    )
    s.text(
        40,
        y + 30,
        "本行程表暨收據為電子機票之憑證，請妥善保存。出發當日請提早 2 小時至機場辦理報到。",
        size=8.5,
        color=GRAY,
    )
    s.text(
        40,
        y + 44,
        "This itinerary receipt is your record of the electronic ticket. Please keep it for your reference.",
        size=7.5,
        color=GRAY,
    )
    s.footer()


def boarding_certificate(doc: pymupdf.Document) -> None:
    s = Sheet(doc)
    airline_header(s, "搭機證明", "CERTIFICATE OF BOARDING")
    s.text(40, 100, "證明編號 No.：TPE-COB-20260712-0087", size=9, color=GRAY)
    s.text(40, 130, "茲證明下列旅客確實搭乘本公司班機，特此證明。", size=11)
    s.text(
        40,
        146,
        "This is to certify that the passenger below travelled on the following flight.",
        size=8.5,
        color=GRAY,
    )
    y = rows(
        s,
        40,
        168,
        [
            ("Passenger Name", "旅客：陳怡君　CHEN/YICHUN MS"),
            ("Ticket Number", "票號：999-2100000000"),
            ("Flight No. / Date", "班機：ZZ 198　日期：2026-07-10"),
            ("Sector", "航段：東京成田 NRT → 台北桃園 TPE"),
            ("Seat / Class", "座位：32A　艙等：經濟艙"),
            ("Date of Issue", "開立日期：2026-07-12"),
        ],
    )
    s.text(330, y + 70, "台北營業處 Taipei Office", size=10)
    s.stamp(500, y + 120, AIRLINE_EN[:6], "台北營業處", "2026.07.12")
    s.footer()


def receipt(doc: pymupdf.Document) -> None:
    s = Sheet(doc, 226, 420)
    lines = [
        ("示範便利商店", 13, True),
        ("成田機場第一航廈店", 9, False),
        ("統一編號 12345678", 8, False),
        ("電子發票證明聯", 11, True),
        ("2026-07-10 11:42:08", 8, False),
        ("發票號碼 ZZ-12345678", 9, False),
        ("隨機碼 3825　總計 64", 8, False),
    ]
    y = 30
    for t, size, bold in lines:
        w = (
            len(t) * size
            if not t.isascii()
            else pymupdf.get_text_length(t, fontsize=size)
        )
        s.text(max(12, (226 - w) / 2), y, t, size=size, bold=bold)
        y += size + 8
    s.barcode(28, y, 170, 22, seed=64)
    y += 40
    s.line(12, y, 214, y)
    y += 16
    for item, price in (("礦泉水 600ml", "25"), ("御飯糰 鮭魚", "39")):
        s.text(14, y, item, size=9)
        s.text(185, y, price, size=9)
        y += 16
    s.line(12, y, 214, y)
    y += 16
    for k, v in (("合計", "64"), ("現金", "100"), ("找零", "36")):
        s.text(14, y, k, size=9, bold=k == "合計")
        s.text(185, y, v, size=9, bold=k == "合計")
        y += 16
    s.text(14, y + 10, "退貨請持本聯及商品至原門市辦理", size=7, color=GRAY)
    s.text(8, 412, "測試範例（資料虛構）SAMPLE ONLY", size=6, color=GRAY)


def claim_form(doc: pymupdf.Document) -> None:
    """富邦「個人保險理賠申請書」第 1 頁，用手寫風格字型填上假資料。"""
    blank = pymupdf.open(BLANK_FORM)
    doc.insert_pdf(blank, from_page=0, to_page=0)
    page = doc[-1]
    page.insert_font(fontname="H", fontbuffer=font(FONT_HAND))
    rnd = random.Random(1105)

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
        # 打勾：□ 的左上角座標
        p0 = pymupdf.Point(box_x + 1.5, box_y + 5.5)
        p1 = pymupdf.Point(box_x + 4.5, box_y + 9.5)
        p2 = pymupdf.Point(box_x + 11, box_y - 1.5)
        page.draw_polyline([p0, p1, p2], color=INK, width=1.3)

    tick(364, 74)  # 個人保險
    tick(207, 87)  # F 旅遊不便險
    tick(472, 129)  # 事故發生地點：海外
    hand(503, 138, "日本成田機場", 9)
    for x, v in ((86, "115"), (122, "7"), (148, "10"), (183, "9"), (212, "30")):
        hand(x, 156, v)  # 事故發生：年月日時分
    hand(98, 180, "陳怡君", 12)  # 被保險人
    for x, v in ((204, "79"), (241, "3"), (269, "12")):
        hand(x, 180, v)  # 出生年月日
    hand(346, 180, "A223456789", 10.5)
    tick(482, 165)  # 就診身分：健保
    hand(92, 204, "同被保險人", 10)  # 事故人
    hand(498, 205, "本人", 10)
    hand(106, 224, "02-2345-6789", 9.5)  # 市話
    hand(262, 224, "0912-345-678", 10)  # 手機
    hand(86, 239, "106", 9)  # 郵遞區號
    hand(143, 252, "台北", 10)
    hand(203, 252, "大安", 10)
    hand(264, 248, "復興南路一段 100 號 5 樓", 10)
    hand(114, 267, "yichun.chen@example.com", 9.5)
    tick(165, 289)  # 是否投保其它保險公司：否
    tick(335, 304)  # 工作中發生：否
    for i, s in enumerate(
        (
            "7/10 從東京成田機場搭 ZZ198 回台北，原定 10:30 起飛，",
            "航空公司說因為天候不佳(強風)延後，實際 16:45 才起飛，",
            "在機場等了 6 小時多，自己買了午餐和晚餐。航空公司開的證明附在後面。",
        )
    ):
        hand(38, 330 + i * 15, s, 10)
    tick(55, 392)  # 付款方式：匯款
    tick(356, 392)  # 帳戶為：受益人
    hand(92, 415, "陳怡君 / A223456789", 10)  # 戶名／身分證號
    hand(362, 427, "示範商業", 9.5)  # ○○銀行
    hand(478, 427, "大安", 9.5)  # ○○分行
    hand(128, 447, "999", 10)  # 金融機構代號
    hand(292, 447, "1234-5678-9012", 10)  # 帳號
    hand(146, 692, "陳怡君", 14)  # 立同意書人（被保險人／受益人簽章）
    hand(152, 751, "陳怡君", 11)  # 送件人
    for x, v in ((456, "115"), (507, "7"), (541, "15")):
        hand(x, 779, v)  # 中華民國年月日
    page.insert_font(fontname="L", fontbuffer=font(FONT_LIGHT))
    page.insert_text((24, 836), FOOTER, fontname="L", fontsize=6, color=GRAY)


# ---- 有問題的版本：讓 6 號在不同步驟出現不同結果 ----

PASSWORD = "0710"  # 有密碼的範例：開檔密碼（使用者自己打開看得到內容，6 號讀不到）


def baggage_delay(doc: pymupdf.Document) -> None:
    """行李延誤證明：雖然也有「延誤證明」，仍不可對到班機延誤的 D01。"""
    s = Sheet(doc)
    airline_header(s, "行李延誤證明書", "BAGGAGE DELAY CERTIFICATE")
    s.text(40, 100, "行李事故報告編號 PIR No.：TPEZZ41873", size=9, color=GRAY)
    s.text(
        40, 128, "茲證明下列旅客之託運行李未隨班機抵達，延誤送達，特此證明。", size=11
    )
    s.text(
        40,
        144,
        "This is to certify that the checked baggage of the passenger below was delayed.",
        size=8.5,
        color=GRAY,
    )
    y = rows(
        s,
        40,
        166,
        [
            ("Passenger Name", "旅客姓名：陳怡君　CHEN/YICHUN MS"),
            ("Flight No. / Date", "班機：ZZ 198　日期：2026-07-10"),
            ("Sector", "航段：東京成田 NRT → 台北桃園 TPE"),
            ("Bag Tag No.", "行李牌號碼：ZZ 412873"),
            ("Bag Type / Color", "行李：硬殼行李箱　灰色　23KG"),
            ("Reported at", "申報時間：2026-07-10 20:15　桃園機場第二航廈"),
            ("Delivered at", "送達時間：2026-07-12 14:30（送至旅客住處）"),
            ("Length of Delay", "行李延誤時間：約 42 小時"),
            ("Issued at", "開立單位：桃園機場行李服務處 Baggage Service"),
        ],
    )
    s.text(
        40,
        y + 30,
        "註：本證明僅證明行李延誤送達事實，供旅客向保險公司申請行李延誤理賠使用。",
        size=9,
        color=GRAY,
    )
    s.text(330, y + 80, "行李服務處 Baggage Service：", size=10)
    s.page.insert_font(fontname="H", fontbuffer=font(FONT_HAND))
    s.page.insert_text((480, y + 80), "王佩珊", fontname="H", fontsize=15, color=INK)
    s.stamp(500, y + 130, AIRLINE_EN[:6], "行李服務處", "2026.07.12")
    s.footer()


def ticket_boarding(doc: pymupdf.Document) -> None:
    """機票和登機證印在同一張：辨識出兩者後，這一份即可完成 D02 待辦。"""
    s = Sheet(doc)
    airline_header(s, "機票暨登機證", "E-TICKET & BOARDING PASS")
    y = rows(
        s,
        40,
        92,
        [
            ("Passenger", "旅客姓名：陳怡君　CHEN/YICHUN MS"),
            ("Ticket Number", "票號：999-2100000000"),
            ("Booking Reference", "訂位代號：K7Q2MD"),
            ("Flight / Date", "班機：ZZ 198　日期：2026-07-10"),
            ("Sector", "航段：東京成田 NRT → 台北桃園 TPE"),
            ("Departure", "起飛時間：10:30　登機時間：10:00"),
            ("Gate / Seat", "登機門：21　座位：32A　艙等：Y 經濟"),
            ("Baggage", "託運行李：23KG"),
        ],
    )
    y += 30
    s.box((40, y, 555, y + 120), color=NAVY, width=1)
    s.text(52, y + 22, "BOARDING PASS", size=11, bold=True, color=NAVY)
    s.text(52, y + 46, "CHEN/YICHUN MS", size=12, bold=True)
    s.text(52, y + 70, "NRT → TPE　ZZ198　10JUL　SEAT 32A　GATE 21", size=11)
    s.text(52, y + 90, "SEQ 087　ETKT 999 2100000000", size=8, color=GRAY)
    s.barcode(360, y + 18, 180, 60, seed=4021)
    s.text(
        40,
        y + 150,
        "本單據於自助報到機列印，請於登機時出示。Please present this document at the gate.",
        size=8.5,
        color=GRAY,
    )
    s.footer()


def ticket_locked(doc: pymupdf.Document) -> None:
    """電子機票加上開檔密碼（像有些航空公司寄來的 PDF）；存檔時才加密，見 main。"""
    e_ticket(doc)


SAMPLE_FILES = {
    "delay": lambda d: delay_certificate(d, with_times=True),
    "delay_missing": lambda d: delay_certificate(d, with_times=False),
    "boarding_pass": boarding_pass,
    "ticket": e_ticket,
    "boarding_proof": boarding_certificate,
    "claim_form": claim_form,
    "receipt": receipt,
    "baggage_delay": baggage_delay,
    "ticket_boarding": ticket_boarding,
    "ticket_locked": ticket_locked,
}
LOCKED = {"ticket_locked"}


# 從 delay.pdf 刪掉幾行做出的延誤證明（不用字型，任何電腦都能重做）：檔名 → 要刪掉的文字
DELAY_REDACTED = {
    # 原定、實際起飛時間與延誤時數都沒有：不合格（合格規範「延誤期間」）
    "delay_no_period": (
        "Scheduled Departure (STD)",
        "原定起飛時間：10:30（當地時間）",
        "Actual Departure (ATD)",
        "實際起飛時間：16:45（當地時間）",
        "Length of Delay",
        "延誤時間：6 小時 15 分",
    ),
    # 沒寫延誤原因：照樣通過，附提醒（合格規範「延誤原因」只提醒）
    "delay_no_reason": ("Reason", "延誤原因：天候不佳（成田機場強風）Adverse weather"),
}


def make_redacted() -> None:
    for name, texts in DELAY_REDACTED.items():
        doc = pymupdf.open(HERE / "delay.pdf")
        page = doc[0]
        for text in texts:
            hits = page.search_for(text)
            if not hits:
                raise ValueError(f"delay.pdf 找不到要刪的文字：{text}")
            for rect in hits:
                page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        out = HERE / f"{name}.pdf"
        doc.save(out, garbage=4, deflate=True)
        logger.info("%s：%d KB", out.name, out.stat().st_size // 1024)


# 照片版：把上面的 PDF 轉成圖，模擬手機拍照會遇到的問題，存成 JPG（送 Azure 讀字）
def _page_image(name: str, dpi: int = 150) -> Image.Image:
    with pymupdf.open(HERE / f"{name}.pdf") as doc:
        pix = doc[0].get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _perspective_coeffs(
    dst: list[tuple[float, float]], src: list[tuple[float, float]]
) -> list[float]:
    """Image.transform 的 PERSPECTIVE 係數：輸出圖上的 dst 四角對到原圖的 src 四角。"""
    a = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    b = [c for point in src for c in point]
    return np.linalg.solve(np.array(a, float), np.array(b, float)).tolist()


def on_table(page: Image.Image, tilt: float) -> Image.Image:
    """把紙放到桌上斜斜拍：四角往內縮成梯形，紙外是灰色桌面。"""
    w, h = page.size
    pad = int(w * 0.08)
    out_w, out_h = w + 2 * pad, h + 2 * pad
    # 上緣離鏡頭遠，看起來比較窄；再整張轉一點
    corners = [
        (pad + w * tilt, pad + h * 0.02),
        (pad + w * (1 - tilt * 0.6), pad),
        (pad + w * (1 + 0.02), pad + h),
        (pad - w * 0.03, pad + h * (1 - 0.01)),
    ]
    coeffs = _perspective_coeffs(corners, [(0, 0), (w, 0), (w, h), (0, h)])
    warped = page.transform(
        (out_w, out_h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    mask = Image.new("L", page.size, 255).transform(
        (out_w, out_h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC
    )
    table = Image.new("RGB", (out_w, out_h), (92, 84, 76))
    table.paste(warped, mask=mask)
    return table


def shadow(img: Image.Image, strength: float) -> Image.Image:
    """手和手機擋到光：從左下角往右上變亮的陰影。"""
    w, h = img.size
    x = np.linspace(0, 1, w)[None, :]
    y = np.linspace(0, 1, h)[:, None]
    dark = np.clip(1 - strength * np.clip((1 - x) * 0.9 + y * 0.6 - 0.5, 0, 1), 0, 1)
    arr = np.asarray(img, float) * dark[..., None]
    return Image.fromarray(arr.astype(np.uint8))


def glare(img: Image.Image, center: tuple[float, float], radius: float) -> Image.Image:
    """燈光反光：一塊白色亮斑（中間幾乎全白，字看不到）。"""
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - center[0] * w, (yy - center[1] * h) * 1.4) / (radius * w)
    light = np.clip(2.2 - 1.6 * d, 0, 1) ** 1.5
    arr = np.asarray(img, float)
    arr = arr + (255 - arr) * light[..., None]
    return Image.fromarray(arr.astype(np.uint8))


def noisy(img: Image.Image, seed: int) -> Image.Image:
    """手機感光元件的雜訊，讓照片不要太乾淨。"""
    rng = np.random.default_rng(seed)
    arr = np.asarray(img, float) + rng.normal(0, 4, (*img.size[::-1], 1))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def save_jpg(img: Image.Image, out: Path, max_side: int = 1600) -> None:
    img.thumbnail((max_side, max_side))
    img.save(out, "JPEG", quality=80, optimize=True)


PHOTO_FILES = {
    # 手機拍登機證：斜拍＋陰影，字還清楚
    "photo_boarding_pass": lambda: noisy(
        shadow(on_table(_page_image("boarding_pass"), tilt=0.06), 0.45), 21
    ),
    # 延誤證明被燈光反光：亮斑蓋在起飛、抵達時間上
    "photo_delay_glare": lambda: noisy(
        glare(on_table(_page_image("delay"), tilt=0.03), (0.5, 0.385), 0.2), 22
    ),
    # 電子機票拍糊了：手震
    "photo_ticket_blurry": lambda: (
        on_table(_page_image("ticket", dpi=100), 0.04)
        .filter(ImageFilter.GaussianBlur(4.5))
        .resize((500, 700))
    ),
    # 手寫的理賠申請書拍照
    "photo_claim_form": lambda: noisy(
        shadow(on_table(_page_image("claim_form", dpi=200), tilt=0.04), 0.3), 24
    ),
}


def make_photos() -> None:
    for name, build in PHOTO_FILES.items():
        out = HERE / f"{name}.jpg"
        save_jpg(build(), out)
        logger.info("%s：%d KB", out.name, out.stat().st_size // 1024)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name, build in SAMPLE_FILES.items():
        doc = pymupdf.open()
        build(doc)
        doc.subset_fonts()  # 再裁成這一份實際用到的字
        out = HERE / f"{name}.pdf"
        if name in LOCKED:
            doc.save(
                out,
                garbage=4,
                deflate=True,
                encryption=5,  # AES-256（pymupdf 的 PDF_ENCRYPT_AES_256，型別檔沒列出）
                user_pw=PASSWORD,
                owner_pw=PASSWORD,
            )
        else:
            doc.save(out, garbage=4, deflate=True)
        logger.info("%s：%d KB", out.name, out.stat().st_size // 1024)
    make_redacted()
    make_photos()


if __name__ == "__main__":
    main()

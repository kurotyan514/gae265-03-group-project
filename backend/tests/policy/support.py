"""保單測試的假資料：全部是構造的，不含任何真實個資。"""

import pymupdf

FAKE_NAME = "王小明"
FAKE_SHORT_NAME = "小明"
FAKE_BENEFICIARY = "陳大華"
FAKE_ID = "A123456789"
FAKE_POLICY_NO = "050026CT200R3446"
FAKE_MOBILE = "0912-345-678"
FAKE_LANDLINE = "02-2345-6789"
FAKE_EMAIL = "wang.xiaoming@example.com"
FAKE_ADDRESS = "台北市中山區南京東路一段100號5樓"
FAKE_STAFF_NO = "0013343"

# 保單首頁（位置排序後「標籤：值」在同一行）
SUMMARY_LAYOUT = f"""旅行綜合險保險單
保單號碼      : {FAKE_POLICY_NO}
被保險人      : {FAKE_NAME}
通訊地址      : {FAKE_ADDRESS}
要保人        : {FAKE_SHORT_NAME}
要保人與被保人關係 :本人
身分證號     : {FAKE_ID}
聯絡電話：{FAKE_MOBILE}　市話 {FAKE_LANDLINE}
電子郵件 {FAKE_EMAIL}
免費申訴電話:0800-009-888
列印人員：{FAKE_STAFF_NO}
受益人姓名        關係         備註
- - - - - - - - - - - - - - - - - - -
{FAKE_BENEFICIARY}        配偶
T068 旅行平安保險  每一人死亡失能  6,000,000元
"""

# 同一頁依原本閱讀順序：標籤與值分在不同行，收據上姓名單獨印出
SUMMARY_READING = f"""旅行綜合險保險單
保單號碼      :
被保險人      :
{FAKE_NAME}
收據 {FAKE_NAME}
{FAKE_POLICY_NO}  第3頁共22頁
T068 旅行平安保險  每一人死亡失能  6,000,000元
"""

PII = [
    FAKE_NAME,
    FAKE_SHORT_NAME,
    FAKE_BENEFICIARY,
    FAKE_ID,
    FAKE_POLICY_NO,
    FAKE_MOBILE,
    FAKE_LANDLINE,
    FAKE_EMAIL,
    FAKE_ADDRESS,
    FAKE_STAFF_NO,
]


def clause_pages(
    n_articles: int = 6, product: str = "T999_富邦產物測試旅行平安保險"
) -> list[str]:
    """附條款全文的頁面：第一頁有商品標題與第一條，之後條號遞增。"""
    body = "\n".join(
        f"第{'一二三四五六七八九十'[i]}條 條文{i + 1}\n本公司於被保險人發生事故時給付保險金，金額以保險單所載為準。"
        for i in range(n_articles)
    )
    return [f"{product}\n保單條款\n{body}"]


def make_pdf(pages: list[str]) -> bytes:
    """有文字層的 PDF（內建繁中字型）。"""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        for i, line in enumerate(text.splitlines()):
            page.insert_text((40, 60 + i * 16), line, fontname="china-t", fontsize=10)
    return doc.tobytes()


def make_scanned_pdf() -> bytes:
    """只有圖片、沒有文字層的 PDF。"""
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    page.insert_image(page.rect, pixmap=pix)
    return doc.tobytes()


ADVANCED_CODES = [
    "T068", "T070", "T147", "TA45", "TA46", "TA47", "TA48", "TA49", "TA50",
    "TA28", "TA29", "TA30", "TA31", "TA33", "TA34", "TA37", "T113", "T115", "TA38",
]  # fmt: skip
BASIC_CODES = [
    "T068", "T070", "T147", "TA45", "TA46", "TA47", "TA48", "TA49", "TA50",
    "TA28", "TA29", "TA37", "T113", "T115", "TA38",
]  # fmt: skip


DEFAULT_PERIOD = "自民國115年05月28日9時0分起至民國115年06月05日9時0分止"
DEFAULT_COUNTRIES = ["日本(本州)", "日本(九州、四國)", "日本(北海道)", "日本(沖繩)"]
PRODUCT_NAME = "【官網】國外旅平險_C方案_加購_115.04版(含法傳)"
# 附加條款名稱太長，PDF 會折行（折行處在詞中間）
RIDER_LINES = [
    "傷害保險恐怖主義行為保險限額給付附加條款、個人海外旅行不便保險班機延誤理賠文",
    "件簡化附加條款",
]
RIDERS = [
    "傷害保險恐怖主義行為保險限額給付附加條款",
    "個人海外旅行不便保險班機延誤理賠文件簡化附加條款",
]
COUNTRY_NUMBERS = "一二三四五六七八九十"


def fubon_policy_text(
    codes: list[str],
    sum_insured: str = "6,000,000",
    *,
    period: str | None = DEFAULT_PERIOD,
    countries: list[str] | None = None,
    product_name: str | None = PRODUCT_NAME,
    rider_lines: list[str] | None = None,
) -> str:
    """富邦保單首頁的版面：保險期間、旅遊國家、商品名稱與附加條款、承保內容表（代碼獨佔一行），
    後面附條款原文（含不在表上的代碼）。國家、附加條款不傳就用預設值，傳空清單代表保單上沒印。
    """
    countries = DEFAULT_COUNTRIES if countries is None else countries
    rider_lines = RIDER_LINES if rider_lines is None else rider_lines
    rows: list[str] = []
    for code in codes:
        rows += [code, f"{code} 的險種名稱"]
        if code == "T068":
            rows += ["旅行平安保險", "每一人死亡失能", f"{sum_insured}元"]
        else:
            rows += ["定額給付", "10,000元"]
    head = ["旅行綜合險保險單", "保單號碼    :", "保險期間    :"]
    if period:
        head.append(period)
    head += ["要保人與被保人關係 :本人"]
    head += [f"旅遊國家{COUNTRY_NUMBERS[i]} :{c}" for i, c in enumerate(countries)]
    head += ["總投保人數:", "1人", "總保險費: 1,143元", "序號 :"]
    if product_name:
        head.append("0001" + "\u3000" * 14 + product_name)
    head += ["主被保險人：", "適用附加條款:", *rider_lines, "身故受益人"]
    return "\n".join(
        [
            *head,
            "承保內容：( 幣別：新台幣)",
            "險種項目                                承保範圍            保險金額   自負額     保險費",
            *rows,
            "每人保費",
            "1,143元",
            "贈送內容：SOS緊急救援服務 美金30000元",
            # 附的條款：商品全名與不在表上的代碼都會出現，比對不能被它們影響
            "富邦產物旅行平安保險 保單條款 T112 TA13",
            "富邦產物享樂個人海外旅行不便保險 富邦產物安心個人旅行綜合保險-甲型",
        ]
    )

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

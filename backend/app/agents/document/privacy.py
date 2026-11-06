"""6 號自己的出口去識別化（#65、ADR-0009、ADR-0022）。

讀出的文件文字送進 LLM、寫進 log 之前都要經過這裡。`app.policy.deidentify` 不改，這裡補兩種它沒處理的情況：

1. 被換行拆開的姓名：照片辨識常把「王小明」讀成「王」「小明」兩行，標籤後面只剩一個字就認不出是姓名。
   標籤後的片段與下一行開頭接起來是二到四個字時當成姓名，再把文件裡所有拆開或沒拆開的寫法都遮掉。
2. 共用規則沒有的標籤：「旅客：王小明」「乘客：…」，以及登機證上的英文姓名格式「WANG/XIAOMING MR」。
3. 檔名：使用者上傳的原檔名常含姓名（例如「王小明_登機證.jpg」）。檔名裡不是文件關鍵字的中文詞當成姓名遮掉。
4. 手寫的申請書：值寫在格子裡、標籤後面沒有冒號，讀出來姓名常自己一行。緊接在身分證字號前面的二到四個字
   （例如戶名欄「陳怡君 / A223456789」）當成姓名，再把文件裡所有同樣的姓名遮掉。
   地址也沒有「地址：」標籤，而且手寫常留空白（「復興南路一段 100 號 5 樓」），用「○○路／街…號」的格式遮掉。
5. 銀行帳號：申請書的匯款帳號常分段寫（「1234-5678-9012」），標籤又常在別行。
   用連字號或空白分成幾段、總共 10～16 碼的數字當成帳號；電話先由共用規則換掉，不會被當成帳號。
6. 出生日期：「出生79年 3月12日」「出生日期：1990/03/12」。只看「出生」標籤，事故日期要留著判斷理賠。
   已知限制：電子 PDF 上年、月、日各自寫在格子裡，讀出來散在不同行，認不出是生日。

`reason` 一律用固定句子（見 recognizer），不放文件內容。
"""

import re

from app.agents.document.codes import SPECS
from app.policy.deidentify import ADDRESS, NAME, deidentify_text, find_values

FILE_NAME = "〔檔名〕"
ACCOUNT = "〔帳號〕"
BIRTH_DATE = "〔出生日期〕"

_SPACE = r"[ \t　]*"
_LABELS = r"(?:主?被保險人|被保人|要保人|申請人|旅客姓名|乘客姓名|姓名|受益人|戶名|持卡人|旅客|乘客)"
# 理賠文件上常見、共用規則沒有的姓名標籤（旅客、乘客）；值在同一行
_LABELED_NAME_RE = re.compile(
    rf"{_LABELS}[ \t\u3000]*[:：][ \t\u3000]*([一-鿿]{{2,4}})(?![一-鿿])"
)
# 航空公司的英文姓名格式：WANG/XIAOMING、WANG/XIAO MING MR
_AIRLINE_NAME_RE = re.compile(
    r"\b[A-Z]{2,}/[A-Z]{2,}(?: [A-Z]{2,})?(?: (?:MR|MRS|MS|MISS|MSTR))?\b"
)
# 標籤後面只剩一到三個字，下一行開頭接著一到三個字：合起來二到四個字才可能是被拆開的姓名
_BROKEN_NAME_RE = re.compile(
    rf"{_LABELS}{_SPACE}[:：]{_SPACE}([一-鿿]{{1,3}}){_SPACE}\n{_SPACE}([一-鿿]{{1,3}})(?![一-鿿])"
)
# 姓名緊接身分證字號：「陳怡君 / A223456789」「陳怡君 A223456789」
_NAME_BEFORE_ID_RE = re.compile(
    r"(?<![一-鿿])([一-鿿]{2,4})[ \t\u3000]*[/／,，]?[ \t\u3000]*[A-Z][12]\d{8}(?![A-Za-z0-9])"
)
# 沒有標籤的地址：路或街開頭到「號」，中間可以有段、巷、弄與空白
_ROAD_ADDRESS_RE = re.compile(
    r"[一-鿿]{1,6}[路街](?:[一二三四五六七八九十]段)?(?:\s*\d+\s*巷)?(?:\s*\d+\s*弄)?"
    r"\s*\d+(?:之\d+)?\s*號(?:\s*\d+\s*樓(?:之\d+)?)?"
)
# 分段寫的帳號：至少兩段、每段二到六碼；前後不能接英數或連字號（證明編號 NRT-DLY-20260710-0412 不算）
_ACCOUNT_RE = re.compile(r"(?<![\w-])\d{2,6}(?:[- ]\d{2,6}){1,5}(?![\w-])")
_ACCOUNT_DIGITS = range(10, 17)
# 出生日期：民國「79年3月12日」或西元「1990/03/12」
_BIRTH_RE = re.compile(
    rf"(出生(?:日期|年月日)?{_SPACE}[:：]?{_SPACE})"
    rf"(?:\d{{2,3}}{_SPACE}年{_SPACE}\d{{1,2}}{_SPACE}月{_SPACE}\d{{1,2}}{_SPACE}日"
    r"|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2})"
)
# 欄位名稱不是姓名（「身分證號 A123456789」）
_NOT_NAME_CHARS = set("證號碼編統")
_FILE_TOKEN_RE = re.compile(r"[一-鿿]{2,4}|[A-Za-z]{2,}(?: [A-Za-z]{2,})*")
# 檔名裡常見、不是姓名的詞
_FILE_WORDS = {
    k.lower()
    for spec in SPECS.values()
    for p in spec.parts
    for k in (*p.keywords, p.label)
} | {
    "證明",
    "收據",
    "掃描",
    "照片",
    "文件",
    "副本",
    "影本",
    "正本",
    "截圖",
    "scan",
    "img",
    "image",
    "photo",
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "copy",
    "screenshot",
    "boarding",
    "pass",
    "ticket",
    "flight",
    "delay",
    "certificate",
    "claim",
    "form",
    "final",
    "new",
}


def broken_names(text: str) -> set[str]:
    """標籤後面被換行拆開的姓名，例如「被保險人：王」「小明」→ 王小明。"""
    names = set()
    for first, rest in _BROKEN_NAME_RE.findall(text):
        name = first + rest
        if 2 <= len(name) <= 4:
            names.add(name)
    return names


def names_before_id(text: str) -> set[str]:
    """緊接在身分證字號前面、不是欄位名稱的二到四個字。"""
    return {n for n in _NAME_BEFORE_ID_RE.findall(text) if not _NOT_NAME_CHARS & set(n)}


def file_name_words(file_name: str) -> set[str]:
    """檔名裡可能是姓名的詞（去掉副檔名與文件關鍵字）。"""
    stem = file_name.rsplit(".", 1)[0]
    words = set()
    for token in _FILE_TOKEN_RE.findall(stem):
        lowered = token.lower()
        if lowered in _FILE_WORDS or any(w in lowered for w in _FILE_WORDS):
            continue
        words.add(token)
    return words


def _split_pattern(name: str) -> re.Pattern[str]:
    """「王小明」也比對「王\\n小明」「王小\\n明」等被換行拆開的寫法。"""
    sep = rf"{_SPACE}\n{_SPACE}"
    return re.compile(f"(?:{sep})?".join(re.escape(c) for c in name))


def deidentify_document_text(text: str, file_name: str | None = None) -> str:
    """遮掉讀出的文字裡的個資，保留原本的換行。"""
    if file_name:
        text = text.replace(file_name, FILE_NAME)
        # 檔名本身只是文件名稱（例如「申請書.pdf」）時，不能把內文的同一個詞也遮掉
        if file_name_words(file_name):
            text = text.replace(file_name.rsplit(".", 1)[0], FILE_NAME)
    # 英文姓名格式要先整段換掉：共用規則會從「姓名：CHEN/YICHUN」只取出 CHEN，先換會留下 /YICHUN
    text = _AIRLINE_NAME_RE.sub(NAME, text)
    text = _ROAD_ADDRESS_RE.sub(ADDRESS, text)
    values = find_values([text])
    names = (
        set(values.get(NAME, set()))
        | broken_names(text)
        | set(_LABELED_NAME_RE.findall(text))
        | names_before_id(text)
    )
    if file_name:
        names |= {w for w in file_name_words(file_name) if len(w) >= 2}
    # 拆開的姓名先換（長的先），再交給共用的規則處理其他個資
    for name in sorted(names, key=len, reverse=True):
        text = _split_pattern(name).sub(NAME, text)
    values[NAME] = names
    text = _BIRTH_RE.sub(rf"\g<1>{BIRTH_DATE}", text)
    text = deidentify_text(text, values)
    return _ACCOUNT_RE.sub(_mask_account, text)


def _mask_account(m: re.Match[str]) -> str:
    digits = sum(c.isdigit() for c in m.group())
    return ACCOUNT if digits in _ACCOUNT_DIGITS else m.group()

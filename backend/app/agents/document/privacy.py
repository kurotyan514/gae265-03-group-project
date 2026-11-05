"""6 號自己的出口去識別化（#65、ADR-0009、ADR-0022）。

讀出的文件文字送進 LLM、寫進 log 之前都要經過這裡。`app.policy.deidentify` 不改，這裡補兩種它沒處理的情況：

1. 被換行拆開的姓名：照片辨識常把「王小明」讀成「王」「小明」兩行，標籤後面只剩一個字就認不出是姓名。
   標籤後的片段與下一行開頭接起來是二到四個字時當成姓名，再把文件裡所有拆開或沒拆開的寫法都遮掉。
2. 共用規則沒有的標籤：「旅客：王小明」「乘客：…」，以及登機證上的英文姓名格式「WANG/XIAOMING MR」。
3. 檔名：使用者上傳的原檔名常含姓名（例如「王小明_登機證.jpg」）。檔名裡不是文件關鍵字的中文詞當成姓名遮掉。

`reason` 一律用固定句子（見 recognizer），不放文件內容。
"""

import re

from app.agents.document.codes import SPECS
from app.policy.deidentify import NAME, deidentify_text, find_values

FILE_NAME = "〔檔名〕"

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
    values = find_values([text])
    names = (
        set(values.get(NAME, set()))
        | broken_names(text)
        | set(_LABELED_NAME_RE.findall(text))
    )
    if file_name:
        names |= {w for w in file_name_words(file_name) if len(w) >= 2}
    # 拆開的姓名先換（長的先），再交給共用的規則處理其他個資
    for name in sorted(names, key=len, reverse=True):
        text = _split_pattern(name).sub(NAME, text)
    values[NAME] = names
    text = _AIRLINE_NAME_RE.sub(NAME, text)
    return deidentify_text(text, values)

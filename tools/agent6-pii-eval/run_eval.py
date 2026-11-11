# ruff: noqa: T201  # 命令列工具，結果直接印出來
"""PII 替代方案實測：方案 B（本機 OCR 找個資 → 塗黑 → 才送雲端）與方案 C（只用本機 OCR）。

用法：.venv/bin/python -I scripts/run_eval.py <dataset_dir> <out_dir>

- 只讀 dataset 的 inputs 與 ground_truth（答案只用來「評分」，偵測個資的規則不看答案）。
- 不連網、不呼叫 Azure／LLM；本機 OCR 用 RapidOCR（PaddleOCR 模型的 ONNX 版）。
- 方案 B 沒有 Azure 金鑰，所以「遮完之後雲端讀得準不準」用本機 OCR 重讀遮過的圖代替；
  能確定的是「遮掉了哪些、誤遮了哪些」。
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import pypdfium2 as pdfium
from opencc import OpenCC
from PIL import Image, ImageDraw
from rapidfuzz import fuzz

_T2S = OpenCC("t2s")
# OCR_ENGINE：v4（rapidocr_onnxruntime 預設中文模型）／v6（PP-OCRv6 多語：簡繁日英）／cht（PP-OCRv3 繁中）
OCR_ENGINE = os.environ.get("OCR_ENGINE", "v4")

# 評分用：哪些欄位算個資（ADR-0009：姓名、身分證、保單號碼、電話、email、地址；另加生日、病歷號、證號、卡片識別）
PII_KEYS = {
    "person_name",
    "doctor_name",
    "driver_name",
    "related_person",
    "birth_date",
    "contact",
    "policy_ref",
    "patient_ref",
    "card_ref",
    "licence_ref",
    "applicant_ref",
}

# 偵測用：通用的多語標籤，不是照答案抄的欄位名稱
LABEL_RE = re.compile(
    r"(\bname\b|姓名|氏名|患者|patient|passenger|physician|doctor|醫師|医師|"
    r"driver|駕駛人|運転者|related person|關係人|関係者|聯絡人|"
    r"policy|保單|保険番号|保険証券|passport|護照|旅券|licen[cs]e|駕照|免許|"
    r"\bcard\b|card ref|カード|卡片|卡號|病歷|id no|身分證|身份證|applicant|申請人|申請者|"
    r"birth|出生|生年月日|e-?mail|メール|信箱|phone|\btel\b|電話|address|住所|地址|住址)",
    re.I,
)
# 從 app/policy/deidentify.py 抄來的格式規則
FORMAT_RES = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![A-Za-z0-9])"),
    re.compile(r"(?<!\d)09\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)"),
    re.compile(
        r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{9,}(?![A-Za-z0-9])"
    ),
]
LABEL_MAX_LEN = 24  # 比這長的框不當成「標籤」，避免整段說明文字被當標籤
FUZZ_OK = 90
RENDER_SCALE = 2.0


def t2s(s: str) -> str:
    """簡繁統一成簡體再比對：OCR 模型常把「測」讀成「测」，程式比對時要容忍。"""
    return _T2S.convert(s)


def norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", t2s(unicodedata.normalize("NFKC", str(s)).lower()))


def parts_of(value) -> list[str]:
    if isinstance(value, (int, float)):
        return [str(value), f"{value:,}"]
    return [p for p in (norm(x) for x in str(value).split(" / ")) if p]


def found(part: str, text: str) -> bool:
    if len(part) < 6:
        return part in text
    return part in text or fuzz.partial_ratio(part, text) >= FUZZ_OK


def readable(value, text: str) -> bool:
    if isinstance(value, (int, float)):
        return any(norm(p) in text for p in parts_of(value))
    return all(found(p, text) for p in parts_of(value))


def any_part_readable(value, text: str) -> bool:
    if isinstance(value, (int, float)):
        return readable(value, text)
    return any(found(p, text) for p in parts_of(value))


def load_pages(path: Path, mime: str) -> list[Image.Image]:
    if mime == "application/pdf":
        pdf = pdfium.PdfDocument(path)
        return [p.render(scale=RENDER_SCALE).to_pil().convert("RGB") for p in pdf]
    return [Image.open(path).convert("RGB")]


def pdf_text(path: Path) -> str:
    pdf = pdfium.PdfDocument(path)
    return "\n".join(p.get_textpage().get_text_range() for p in pdf)


def make_engine():
    if OCR_ENGINE == "v4":
        from rapidocr_onnxruntime import RapidOCR as Old

        old = Old()
        return lambda arr: [(q, t, sc) for q, t, sc in (old(arr)[0] or [])]
    from rapidocr import LangRec, OCRVersion, RapidOCR

    if OCR_ENGINE == "v6":
        params = {
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.lang_type": LangRec.CH,
        }
    else:
        params = {
            "Rec.ocr_version": OCRVersion.PPOCRV4,
            "Rec.lang_type": LangRec.CHINESE_CHT,
        }
    new = RapidOCR(params=params)

    def run(arr):
        r = new(arr)
        if r.boxes is None:
            return []
        return [
            (q.tolist(), t, sc)
            for q, t, sc in zip(r.boxes, r.txts, r.scores, strict=True)
        ]

    return run


def run_ocr(engine, img: Image.Image):
    import numpy as np

    boxes = []
    for quad, text, score in engine(np.array(img)):
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        boxes.append(
            {
                "quad": [tuple(map(float, p)) for p in quad],
                "text": text,
                "score": float(score),
                "x0": min(xs),
                "x1": max(xs),
                "y0": min(ys),
                "y1": max(ys),
                "cx": sum(xs) / 4,
                "cy": sum(ys) / 4,
                "h": max(ys) - min(ys),
            }
        )
    return boxes


LABEL_WORDS = [
    "name",
    "姓名",
    "氏名",
    "患者",
    "patient",
    "passenger",
    "physician",
    "doctor",
    "醫師",
    "医師",
    "医师",
    "醫生",
    "driver",
    "駕駛人",
    "運転者",
    "relatedperson",
    "關係人",
    "関係者",
    "聯絡人",
    "policy",
    "保單",
    "保険番号",
    "passport",
    "護照",
    "旅券",
    "licence",
    "license",
    "駕照",
    "免許",
    "card",
    "カード",
    "卡片",
    "卡號",
    "病歷",
    "idno",
    "身分證",
    "身份證",
    "applicant",
    "申請人",
    "申請者",
    "birth",
    "出生",
    "生年月日",
    "email",
    "メール",
    "信箱",
    "phone",
    "電話",
    "address",
    "住所",
    "地址",
    "住址",
]


def _flat(t: str) -> str:
    return re.sub(r"[\s:：()（）]+", "", t2s(unicodedata.normalize("NFKC", t).lower()))


def is_label(t: str) -> bool:
    """像「欄位名稱」的框：短、沒有數字與斜線，且（容錯）含個資標籤字。"""
    raw = t.strip()
    f = _flat(raw)
    if not f or len(f) > 18 or "/" in raw or re.search(r"\d", raw):
        return False
    if re.fullmatch(r"[A-Z0-9-]{6,}", raw):  # TEST-PATIENT-A 這種代碼是值
        return False
    for w in (t2s(w) for w in LABEL_WORDS):
        if w in f:
            return True
        # OCR 讀錯一兩個字（phyaician、係者）
        if len(f) >= 0.6 * len(w) and len(w) >= 3 and fuzz.partial_ratio(w, f) >= 85:
            return True
    return False


def looks_like_any_label(t: str) -> bool:
    return t.strip().endswith((":", "：")) or (is_label(t))


def detect_pii(boxes: list[dict], known: list[str] = ()) -> set[int]:
    """只用規則找個資框：標籤旁（右邊或正下方）的值、格式像個資的框、平台已知的使用者姓名／email。"""
    hit: set[int] = set()
    for i, b in enumerate(boxes):
        t = b["text"].strip()
        if any(r.search(t) for r in FORMAT_RES):
            hit.add(i)
        if not is_label(t):
            continue
        if re.search(r"[:：]\s*\S", t):
            hit.add(i)
        h = max(b["h"], 1)
        right = [
            j
            for j, o in enumerate(boxes)
            if j != i
            and o["x0"] > b["cx"]
            and abs(o["cy"] - b["cy"]) < 0.6 * h
            and o["x0"] - b["x1"] < 16 * h
            and not looks_like_any_label(o["text"])
        ]
        if right:
            hit.add(min(right, key=lambda j: boxes[j]["x0"]))
            continue
        below = [
            j
            for j, o in enumerate(boxes)
            if j != i
            and 0 < o["cy"] - b["cy"] < 2.2 * h
            and o["x0"] < b["x1"]
            and o["x1"] > b["x0"]
        ]
        if below:
            j = min(below, key=lambda j: boxes[j]["cy"])
            if not looks_like_any_label(boxes[j]["text"]):
                hit.add(j)
    # 平台已知的值（事件事實裡的姓名、帳號 email）：出現在哪裡都遮
    parts = [norm(p) for k in known for p in str(k).split(" / ") if len(norm(p)) >= 3]
    for j, o in enumerate(boxes):
        n = norm(o["text"])
        if (
            j not in hit
            and n
            and any(
                p in n or (len(n) >= 3 and fuzz.partial_ratio(p, n) >= 85)
                for p in parts
            )
        ):
            hit.add(j)
    return hit


def mask(img: Image.Image, boxes: list[dict], idx: set[int]) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for i in idx:
        b = boxes[i]
        cx, cy = b["cx"], b["cy"]
        pad = 0.25 * b["h"] + 3
        quad = []
        for x, y in b["quad"]:
            dx, dy = x - cx, y - cy
            quad.append((x + (pad if dx > 0 else -pad), y + (pad if dy > 0 else -pad)))
        draw.polygon(quad, fill=(0, 0, 0))
    return out


def main(dataset: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "masked").mkdir(exist_ok=True)
    cases = json.loads((dataset / "ground_truth" / "answers.json").read_text())["cases"]
    engine = make_engine()
    rows = []
    for c in cases:
        if c["mime_type"] not in ("application/pdf", "image/jpeg", "image/png"):
            continue
        path = dataset / c["input_file"]
        fields = [f for f in c["field_truth"] if f["extraction_expected"] is not None]
        row = {
            k: c[k] for k in ("case_id", "category", "language", "quality", "mime_type")
        }
        row["text_layer"] = c["pdf_text_layer"]

        if c["pdf_text_layer"]:
            # 電子 PDF 不需要 OCR，也不會送雲端；只用來校正比對規則（理論上應全讀到）
            text = norm(pdf_text(path))
            row["baseline_read"] = {
                f["key"]: readable(f["extraction_expected"], text) for f in fields
            }
            rows.append(row)
            continue

        pages = load_pages(path, c["mime_type"])
        t0 = time.perf_counter()
        page_boxes = [run_ocr(engine, p) for p in pages]
        row["ocr_seconds"] = round(time.perf_counter() - t0, 2)

        pre_text = norm("".join(b["text"] for bs in page_boxes for b in bs))
        masked_pages, mask_counts = [], []
        fixture = json.loads(
            (dataset / "fixtures" / f"{c['case_id']}.json").read_text()
        )
        known = [
            f["value"]
            for f in fixture["ctx"]["facts"]
            if f["fact_key"] == "person_name"
        ]
        known.append(fixture["user"]["email"])
        for p, bs in zip(pages, page_boxes, strict=True):
            idx = detect_pii(bs, known)
            mask_counts.append(len(idx))
            masked_pages.append(mask(p, bs, idx))
        for n, mp in enumerate(masked_pages):
            mp.save(out / "masked" / f"{c['case_id']}_p{n + 1}.png")
        t1 = time.perf_counter()
        post_text = norm(
            "".join(b["text"] for mp in masked_pages for b in run_ocr(engine, mp))
        )
        row["mask_seconds"] = round(time.perf_counter() - t1, 2)
        row["masked_boxes"] = sum(mask_counts)

        row["fields"] = []
        for f in fields:
            v = f["extraction_expected"]
            is_pii = f["key"] in PII_KEYS
            row["fields"].append(
                {
                    "key": f["key"],
                    "pii": is_pii,
                    "critical": f["is_critical"],
                    "visibility": f["visibility"],
                    "read_before": readable(v, pre_text),
                    "any_part_before": any_part_readable(v, pre_text),
                    "read_after": readable(v, post_text),
                    "any_part_after": any_part_readable(v, post_text),
                }
            )
        # 答案說看不清楚（null）的欄位：本機 OCR 有沒有硬讀出原值
        row["overread"] = [
            f["key"]
            for f in c["field_truth"]
            if f["extraction_expected"] is None
            and f["generator_value"] not in (None, "")
            and f["visibility"] in ("unreadable",)
            and readable(f["generator_value"], pre_text)
        ]
        rows.append(row)
        print(c["case_id"], row["quality"], f"{row['ocr_seconds']}s", flush=True)

    with (out / "results.jsonl").open("w") as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

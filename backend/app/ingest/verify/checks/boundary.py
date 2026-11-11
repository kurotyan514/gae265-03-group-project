"""3 邊界：條文切割位置是否正確。

- 內文裡出現另一條的標題行 → 混入其他條文
- 開頭／結尾和 PDF 標準答案對不上 → 判斷是被截斷、跑到隔壁條，還是混入隔壁條
- 標題被當成內文

「依第三十二條規定」這類合法引用不是標題行（標題行必須是整行「第N條 短標題」），不會被誤判。
"""

from app.ingest.verify.baseline import Baseline
from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import Finding, Status
from app.ingest.verify.textutil import normalize, parse_number

CHECK = "boundary"
EDGE = 15  # 比對開頭／結尾的字數


def run(ctx: VerifyContext) -> list[Finding]:
    out: list[Finding] = []
    bl = ctx.baseline
    for a in ctx.articles:
        no = a.article_no

        for line in a.content.splitlines():
            m = ctx.profile.article_heading.match(line.strip())
            if m and parse_number(m["no"]) != no:
                out.append(
                    _f(
                        "B1-foreign-heading",
                        f"內文中出現另一條的標題行「{line.strip()}」，疑似混入其他條文",
                        no,
                        "從這一行起的內容應屬於另一條",
                    )
                )
                break

        if not normalize(a.title):
            out.append(
                _f(
                    "B2-no-title",
                    "沒有標題，可能把標題當成了內文",
                    no,
                    "確認標題是否被併入內文第一行",
                    severity="中",
                )
            )

        art = bl.articles.get(no)
        if art is None or not art.agreed or art.a is None:
            continue  # 沒有可信的標準答案：正確性／完整性已回報，這裡不重複判斷
        expected = normalize(art.a.text)
        expected = (
            ctx.with_errata(no, expected) or expected
        )  # 套上勘誤才是「應有的樣子」
        chunk = normalize(a.content)
        title = normalize(art.a.title)
        if title and chunk.startswith(title) and not expected.startswith(title):
            out.append(
                _f(
                    "B2-title-in-body",
                    f"內文開頭是標題「{art.a.title}」，標題被當成內文",
                    no,
                    "把第一行移到標題欄位",
                    severity="中",
                )
            )
            chunk = chunk[len(title) :]
        if chunk == expected or not chunk:
            continue

        numbers = sorted(bl.articles)
        i = numbers.index(no)
        prev_text = _text(bl, numbers[i - 1]) if i > 0 else ""
        next_text = _text(bl, numbers[i + 1]) if i + 1 < len(numbers) else ""
        prev_item, next_item = ctx.neighbors(a)
        prev_chunk = normalize(prev_item.content) if prev_item else ""
        next_chunk = normalize(next_item.content) if next_item else ""
        if f := _head(chunk, expected, prev_text, prev_chunk, no):
            out.append(f)
        if f := _tail(chunk, expected, next_text, next_chunk, no):
            out.append(f)
    return out


def _head(
    chunk: str, expected: str, prev_text: str, prev_chunk: str, no: int
) -> Finding | None:
    if chunk.startswith(expected[:EDGE]) and expected.startswith(chunk[:EDGE]):
        return None
    if expected.endswith(chunk):  # 開頭少了一段
        lost = expected[: len(expected) - len(chunk)]
        if prev_chunk.endswith(lost):
            return _f(
                "B4-head-in-prev",
                f"本條開頭「{lost[:20]}」被切到前一條",
                no,
                "把開頭移回本條",
            )
        return _f(
            "B4-head-cut",
            f"開頭被截斷，少了「{lost[:20]}」",
            no,
            "對照 PDF 補回開頭",
        )
    if chunk.endswith(expected):  # 開頭多了一段
        extra = chunk[: len(chunk) - len(expected)]
        if prev_text.endswith(extra):
            return _f(
                "B3-head-from-prev",
                f"開頭混入了前一條的結尾「{extra[:20]}」",
                no,
                "把這段移回前一條",
            )
        return _f("B3-head-extra", f"開頭多出不屬於本條的文字「{extra[:20]}」", no)
    # 開頭與結尾同時有狀況時，退回用開頭幾個字判斷
    if prev_text and chunk[:EDGE] in prev_text:
        return _f("B3-head-from-prev", "開頭混入了前一條的內容", no, "把這段移回前一條")
    if expected[:EDGE] in chunk:
        return _f("B3-head-extra", "開頭多出不屬於本條的文字", no)
    return _f("B4-head-cut", "開頭與 PDF 不一致（可能被截斷）", no, "對照 PDF 確認開頭")


def _tail(
    chunk: str, expected: str, next_text: str, next_chunk: str, no: int
) -> Finding | None:
    if chunk.endswith(expected[-EDGE:]) and expected.endswith(chunk[-EDGE:]):
        return None
    if expected.startswith(chunk):  # 結尾少了一段
        lost = expected[len(chunk) :]
        if next_chunk.startswith(lost):
            return _f(
                "B5-tail-in-next",
                f"本條結尾「{lost[:20]}」被切到下一條",
                no,
                "把結尾移回本條",
            )
        return _f(
            "B7-tail-cut",
            f"結尾被截斷，少了「{lost[:20]}」",
            no,
            "對照 PDF 補回結尾",
        )
    if chunk.startswith(expected):  # 結尾多了一段
        extra = chunk[len(expected) :]
        if next_text.startswith(extra):
            return _f(
                "B6-tail-from-next",
                f"結尾混入了下一條的開頭「{extra[:20]}」",
                no,
                "把這段移回下一條",
            )
        return _f("B6-tail-extra", f"結尾多出不屬於本條的文字「{extra[:20]}」", no)
    if expected[-EDGE:] in next_chunk:
        return _f("B5-tail-in-next", "本條的結尾被切到下一條", no, "把結尾移回本條")
    if next_text and chunk[-EDGE:] in next_text:
        return _f("B6-tail-from-next", "結尾混入了下一條的內容", no)
    if expected[-EDGE:] in chunk:
        return _f("B6-tail-extra", "結尾多出不屬於本條的文字", no)
    return _f("B7-tail-cut", "結尾與 PDF 不一致（可能被截斷）", no, "對照 PDF 確認結尾")


def _text(bl: Baseline, no: int) -> str:
    return normalize(bl.articles[no].best.text)


def _f(
    rule: str, message: str, no: int, suggestion: str = "", *, severity: str = "高"
) -> Finding:
    return Finding(
        check=CHECK,
        rule=rule,
        status=Status.FAIL,
        severity=severity,
        message=message,
        article_no=no,
        suggestion=suggestion,
    )

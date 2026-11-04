"""讀出文件上的文字（#67、ADR-0012、ADR-0022）。

- 電子 PDF 有文字層：程式自己讀，不送外部服務，每一行信心度當成 1。
- 照片（JPG、PNG）、掃描檔、沒有文字層的 PDF：送 Azure Document Intelligence（read 或 layout，用設定切換）。

日期、時間、航班等欄位一律取自這裡讀出的文字，不由 LLM 產生（ADR-0004）。
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from app.contracts import UploadedFile

PDF = "application/pdf"
IMAGE_TYPES = {"image/jpeg", "image/png"}


class UnreadableFile(Exception):
    """檔案打不開、格式不支援或有密碼；可以請使用者重新上傳。訊息直接給使用者看，不含內容。"""


class OcrUnavailable(Exception):
    """沒有設定 Azure Document Intelligence，照片與掃描檔讀不了。"""


class OcrFailed(Exception):
    """呼叫 Azure 失敗（網路、額度、逾時）。訊息不含文件內容。"""


@dataclass(frozen=True)
class Line:
    text: str
    confidence: float  # 0～1；這一行裡最低的字詞信心度
    handwritten: bool = False


@dataclass(frozen=True)
class ReadResult:
    lines: list[Line]
    source: Literal["pdf_text", "ocr"]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


class OcrClient(Protocol):
    async def read(self, content: bytes, content_type: str) -> ReadResult: ...


def sniff_type(file: UploadedFile) -> str:
    """看檔頭判斷格式；使用者手機傳來的 content_type 不一定可靠。"""
    head = file.content[:8]
    if head.startswith(b"%PDF"):
        return PDF
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return file.content_type


def _pdf_text(content: bytes) -> list[str] | None:
    """電子 PDF 的每一行；沒有文字層回 None（要送 OCR）。"""
    import pymupdf

    try:
        doc = pymupdf.open(stream=content, filetype="pdf")
    except Exception as e:  # pymupdf 對壞檔丟的例外型別不固定
        raise UnreadableFile("檔案無法開啟，請重新上傳") from e
    with doc:
        if doc.needs_pass:
            raise UnreadableFile("這個 PDF 有密碼保護，請先解除後再上傳")
        if doc.page_count == 0:
            raise UnreadableFile("檔案無法開啟，請重新上傳")
        text = "\n".join(str(page.get_text("text")) for page in doc.pages())
    lines = [line for line in text.splitlines() if line.strip()]
    return lines or None


async def read_document(file: UploadedFile, ocr: OcrClient | None) -> ReadResult:
    kind = sniff_type(file)
    if kind == PDF:
        lines = _pdf_text(file.content)
        if lines is not None:
            return ReadResult([Line(t, 1.0) for t in lines], "pdf_text")
    elif kind not in IMAGE_TYPES:
        raise UnreadableFile("只收 JPG、PNG 或 PDF，請換個格式再上傳")
    if ocr is None:
        raise OcrUnavailable
    return await ocr.read(file.content, kind)


class AzureDocumentIntelligence:
    """Azure Document Intelligence 的 prebuilt-read／prebuilt-layout（REST）。

    `transport` 給測試換成假的，不連網。
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        model: Literal["read", "layout"] = "read",
        api_version: str = "2024-11-30",
        transport: httpx.AsyncBaseTransport | None = None,
        poll_interval: float = 1.0,
        timeout: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.api_version = api_version
        self.transport = transport
        self.poll_interval = poll_interval
        self.timeout = timeout

    async def read(self, content: bytes, content_type: str) -> ReadResult:
        url = (
            f"{self.endpoint}/documentintelligence/documentModels/"
            f"prebuilt-{self.model}:analyze?api-version={self.api_version}"
        )
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=30.0
            ) as client:
                started = await client.post(
                    url,
                    content=content,
                    headers=headers | {"Content-Type": content_type},
                )
                if started.status_code != 202:
                    raise OcrFailed(f"文件辨識服務回應 {started.status_code}")
                result_url = started.headers["Operation-Location"]
                waited = 0.0
                while True:
                    polled = await client.get(result_url, headers=headers)
                    polled.raise_for_status()
                    body = polled.json()
                    if body.get("status") == "succeeded":
                        return parse_analyze_result(body.get("analyzeResult", {}))
                    if body.get("status") == "failed":
                        raise OcrFailed("文件辨識服務處理失敗")
                    if waited >= self.timeout:
                        raise OcrFailed("文件辨識服務逾時")
                    await asyncio.sleep(self.poll_interval)
                    waited += self.poll_interval
        except httpx.HTTPError as e:
            raise OcrFailed(f"文件辨識服務連線失敗（{type(e).__name__}）") from e


def _overlaps(a: dict[str, int], spans: list[dict[str, int]]) -> bool:
    start, end = a["offset"], a["offset"] + a["length"]
    return any(s["offset"] < end and start < s["offset"] + s["length"] for s in spans)


def parse_analyze_result(result: dict[str, Any]) -> ReadResult:
    """把 analyzeResult 轉成逐行文字：每行的信心度取行內字詞的最低值，與手寫區段重疊就標成手寫。"""
    handwritten = [
        span
        for style in result.get("styles", [])
        if style.get("isHandwritten")
        for span in style.get("spans", [])
    ]
    lines: list[Line] = []
    for page in result.get("pages", []):
        words = page.get("words", [])
        for line in page.get("lines", []):
            spans = line.get("spans", [])
            confidences = [
                w.get("confidence", 0.0)
                for w in words
                if any(_overlaps(w["span"], [s]) for s in spans)
            ]
            lines.append(
                Line(
                    text=line.get("content", ""),
                    confidence=min(confidences) if confidences else 0.0,
                    handwritten=any(_overlaps(s, handwritten) for s in spans),
                )
            )
    return ReadResult(lines, "ocr")

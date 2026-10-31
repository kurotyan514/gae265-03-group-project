"""路徑、設定檔與險種登記表。公司與險種都從設定檔讀，程式裡不寫死任何一家保險公司。"""

import csv
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
PDF_DIR = DATA_DIR / "pdfs"
RUN_DIR = DATA_DIR / "runs"
REVIEW_FILE = DATA_DIR / "reviews.json"
GOLD_FILE = DATA_DIR / "gold.json"
# 條款勘誤清單（backend 維護）：官網 PDF 與實際保單不同處，匯入時以保單為準
ERRATA_FILE = ROOT.parents[1] / "backend" / "data" / "config" / "clause_errata.json"

# 驗證規則改了就升版，報告會記錄這個版本
RULES_VERSION = "2026.10.31-1"


@dataclass(frozen=True)
class Insurance:
    code: str
    company: str
    name: str
    pdf_file: str  # 相對於 data/pdfs/
    official_url: str = ""
    pdf_sha256: str = ""  # 人工確認過「這份就是官方版本」後填入
    source_note: str = ""

    @property
    def pdf_path(self) -> Path:
        return PDF_DIR / self.pdf_file


@dataclass(frozen=True)
class CompanyProfile:
    name: str
    article_heading: re.Pattern
    chapter_heading: re.Pattern
    max_title_len: int
    drop_lines: tuple[re.Pattern, ...]
    appendix_start: tuple[re.Pattern, ...]
    boilerplate: tuple[re.Pattern, ...] = ()


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    long_chunk_chars: int


def load_registry(path: Path | None = None) -> dict[str, Insurance]:
    path = path or CONFIG_DIR / "insurances.csv"
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    registry: dict[str, Insurance] = {}
    for row in rows:
        code = row["code"].strip()
        if not code:
            continue
        if code in registry:
            raise ValueError(f"險種登記表有重複代碼：{code}")
        registry[code] = Insurance(
            code=code,
            company=row["company"].strip(),
            name=row["insurance_name"].strip(),
            pdf_file=row["pdf_file"].strip(),
            official_url=(row.get("official_url") or "").strip(),
            pdf_sha256=(row.get("pdf_sha256") or "").strip().lower(),
            source_note=(row.get("source_note") or "").strip(),
        )
    return registry


def _profile(name: str, raw: dict) -> CompanyProfile:
    return CompanyProfile(
        name=name,
        article_heading=re.compile(raw["article_heading"]),
        chapter_heading=re.compile(raw["chapter_heading"]),
        max_title_len=int(raw["max_title_len"]),
        drop_lines=tuple(re.compile(p) for p in raw["drop_lines"]),
        appendix_start=tuple(re.compile(p) for p in raw["appendix_start"]),
        boilerplate=tuple(re.compile(p, re.S) for p in raw.get("boilerplate", [])),
    )


def load_profiles(path: Path | None = None) -> dict[str, CompanyProfile]:
    """公司設定 = default 再蓋上該公司自己的設定。key 'default' 給沒有設定的公司用。"""
    path = path or CONFIG_DIR / "companies.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    default = raw["default"]
    profiles = {"default": _profile("default", default)}
    for name, overrides in raw.get("companies", {}).items():
        profiles[name] = _profile(name, {**default, **overrides})
    return profiles


def profile_for(profiles: dict[str, CompanyProfile], company: str) -> CompanyProfile:
    return profiles.get(company, profiles["default"])


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_DIR / "settings.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    local = path.with_name("settings.local.toml")  # 個人設定（不進 git）覆蓋共用設定
    if local.exists():
        with open(local, "rb") as f:
            raw |= tomllib.load(f)
    return Settings(
        api_base_url=raw["api_base_url"].rstrip("/"),
        long_chunk_chars=int(raw["long_chunk_chars"]),
    )


@dataclass(frozen=True)
class Erratum:
    code: str
    article_no: int
    old: str  # 官網 PDF 的原文
    new: str  # 實際保單的文字
    reason: str


def load_errata(path: Path | None = None) -> dict[tuple[str, int], list[Erratum]]:
    """讀勘誤清單；沒有這個檔案時回傳空的（等於沒有勘誤）。"""
    path = path or ERRATA_FILE
    if not path.exists():
        return {}
    out: dict[tuple[str, int], list[Erratum]] = {}
    for row in json.loads(path.read_text(encoding="utf-8"))["errata"]:
        e = Erratum(
            row["insurance"],
            int(row["article_no"]),
            row["old"],
            row["new"],
            row["reason"],
        )
        out.setdefault((e.code, e.article_no), []).append(e)
    return out


def config_fingerprint() -> str:
    """設定檔內容的指紋：報告記錄用，設定改了指紋就不同。"""
    h = hashlib.sha256()
    for name in ("insurances.csv", "companies.toml", "settings.toml"):
        h.update((CONFIG_DIR / name).read_bytes())
    return h.hexdigest()[:12]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

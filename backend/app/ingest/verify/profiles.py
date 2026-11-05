"""各公司 PDF 的版面規則（backend/data/config/verify_profiles.toml）。

驗證用自己的切段規則，不沿用 ingest/clauses.py：避免用同一套邏輯檢查自己。
公司沒有自己的設定就用 default。
"""

import re
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.core.config import settings


class CompanyProfile(BaseModel):
    name: str
    article_heading: re.Pattern[str]
    chapter_heading: re.Pattern[str]
    max_title_len: int
    drop_lines: tuple[re.Pattern[str], ...]
    appendix_start: tuple[re.Pattern[str], ...]
    boilerplate: tuple[re.Pattern[str], ...] = ()


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
    path = path or settings.CONFIG_DIR / "verify_profiles.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    default = raw["default"]
    profiles = {"default": _profile("default", default)}
    for name, overrides in raw.get("companies", {}).items():
        profiles[name] = _profile(name, {**default, **overrides})
    return profiles


@lru_cache
def default_profiles() -> dict[str, CompanyProfile]:
    return load_profiles()


def profile_for(
    company: str | None, profiles: dict[str, CompanyProfile] | None = None
) -> CompanyProfile:
    profiles = profiles or default_profiles()
    return profiles.get(company or "", profiles["default"])

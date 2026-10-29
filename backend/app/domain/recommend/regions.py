"""目的地 → 地區（決定最低保額門檻用）。對照表在 config/regions.json，使用者可自行修改。"""

import json
from pathlib import Path

from app.core.config import settings

DEFAULT_REGION = "japan_europe_us"  # 查不到時採用門檻較高的一邊，寧可多要求保障


def region_of(destination: str, path: Path | None = None) -> tuple[str, bool]:
    """回傳 (地區, 是否為推測)。

    比對方式：別名出現在目的地字串中即命中（「日本北海道」命中「日本」）；
    有多個別名命中時取最長的，避免「大洋洲」搶走「大洋洲小島」。
    """
    path = settings.CONFIG_DIR / "regions.json" if path is None else path
    table: dict[str, list[str]] = json.loads(Path(path).read_text(encoding="utf-8"))
    best_alias, best_region = "", None
    for region, aliases in table.items():
        for alias in aliases:
            if alias in destination and len(alias) > len(best_alias):
                best_alias, best_region = alias, region
    if best_region is None:
        return DEFAULT_REGION, True
    return best_region, False

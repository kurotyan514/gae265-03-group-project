import uuid
from datetime import date

from sqlalchemy import ARRAY, Column, Text
from sqlmodel import Field

from app.models.base import BaseTable


class Comparison(BaseTable, table=True):
    """比較紀錄：一次「出發前：幫我選方案」的旅行規劃、排序過的在意事項與補充說明。

    與保單（policy）各自獨立：比較紀錄是「考慮買什麼」，保單是「實際買了什麼」。
    目的地與在意事項的可選值由 API 用 enum 驗證，不加資料庫 CHECK（enum 改名不用寫 migration）。
    """

    __tablename__ = "comparison"  # pyright: ignore[reportAssignmentType]

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    destination: str = Field(description="目的地名稱（app.domain.destinations）")
    depart_date: date
    return_date: date
    age: int
    concerns: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"),
        description="在意事項名稱（app.domain.benefits.Concern），陣列順序就是重要程度",
    )
    note: str = Field(
        default="", sa_column_kwargs={"server_default": ""}, description="其他在意的事"
    )
    # 推薦結果（ADR-0021）：存檔時天數或在意事項有變才重算。四個都是空的代表還沒推薦。
    # 保費、額度、推薦理由與比較表不存，讀取時依這兩個方案與保額重算。
    recommended_plan_code: str | None = Field(default=None, description="推薦方案 id")
    recommended_sum_insured: int | None = Field(
        default=None, description="推薦方案卡片目前選的身故保額（元）"
    )
    alternative_plan_code: str | None = Field(
        default=None, description="對照方案（次推薦）id"
    )
    alternative_sum_insured: int | None = Field(
        default=None, description="對照方案卡片目前選的身故保額（元）"
    )

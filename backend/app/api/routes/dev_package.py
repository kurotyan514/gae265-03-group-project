"""開發用：7 號打包寄送的範例（/dev/package 頁）。只在非 production 註冊（見 app.api.main）。

不需要登入、不寫資料庫、不連 Google；範例都是虛構的事件資料，信件由 7 號的 build 產生。
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.package import GmailClaimPackager
from app.agents.package.samples import SAMPLES
from app.contracts import ClaimPackage

router = APIRouter(tags=["dev"])


class ClaimPackageSampleOut(BaseModel):
    key: str
    title: str
    description: str
    package: ClaimPackage


@router.get("/dev/package-samples")
async def list_claim_package_samples() -> list[ClaimPackageSampleOut]:
    """7 號在各種情況下產生的送件信（範例內容都是虛構的）。"""
    packager = GmailClaimPackager()
    return [
        ClaimPackageSampleOut(
            key=s.key,
            title=s.title,
            description=s.description,
            package=await packager.build(s.context),
        )
        for s in SAMPLES
    ]

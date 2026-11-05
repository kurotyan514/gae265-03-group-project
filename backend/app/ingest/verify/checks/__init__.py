"""六項檢查。每一項都是 run(ctx) -> list[Finding]，只回報「有狀況」的條文；沒有回報的條文就是通過。"""

from collections.abc import Callable

from app.ingest.verify.checks import (
    accuracy,
    attribution,
    boundary,
    completeness,
    long_article,
    traceability,
)
from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import Finding

ALL: dict[str, Callable[[VerifyContext], list[Finding]]] = {
    "completeness": completeness.run,
    "accuracy": accuracy.run,
    "boundary": boundary.run,
    "attribution": attribution.run,
    "long_article": long_article.run,
    "traceability": traceability.run,
}

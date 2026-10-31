"""六項驗證。每一項都是 run(ctx) -> list[Finding]，只回報「有狀況」的條文；沒有回報的條文就是通過。"""

from validator.checks import (
    accuracy,
    attribution,
    boundary,
    completeness,
    long_chunk,
    traceability,
)

ALL = {
    "completeness": completeness.run,
    "accuracy": accuracy.run,
    "boundary": boundary.run,
    "attribution": attribution.run,
    "long_chunk": long_chunk.run,
    "traceability": traceability.run,
}

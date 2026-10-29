"""關鍵字檢索：中文用連續兩字（bigram）當詞，再用 BM25 計分。"""

import math
import re
from collections import Counter

# 英數字串整段一個詞；一串連續的中文字另外處理
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        piece = m.group()
        if piece.isascii():
            tokens.append(piece.lower())
        else:  # 「滑雪場」→「滑雪」「雪場」；只有一個字的不成詞
            tokens.extend(piece[i : i + 2] for i in range(len(piece) - 1))
    return tokens


class BM25Index:
    """documents 是 (id, 文字) 的清單；search 回傳 (id, 分數)，分數由高到低。"""

    def __init__(
        self, documents: list[tuple[str, str]], k1: float = 1.5, b: float = 0.75
    ):
        self.ids = [doc_id for doc_id, _ in documents]
        self.k1, self.b = k1, b
        self.term_counts = [Counter(tokenize(text)) for _, text in documents]
        self.lengths = [sum(c.values()) for c in self.term_counts]
        self.avg_len = (sum(self.lengths) / len(documents)) if documents else 0.0
        self.doc_freq: Counter[str] = Counter()
        for counts in self.term_counts:
            self.doc_freq.update(counts.keys())

    def __len__(self) -> int:
        return len(self.ids)

    def _idf(self, term: str) -> float:
        n, df = len(self.ids), self.doc_freq[term]
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        terms = sorted(set(tokenize(query)))  # 固定加總順序，浮點分數才可重現
        scored = []
        for doc_id, counts, length in zip(
            self.ids, self.term_counts, self.lengths, strict=True
        ):
            score = 0.0
            for term in terms:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                score += self._idf(term) * tf * (self.k1 + 1) / norm
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

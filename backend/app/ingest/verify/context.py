"""一次驗證需要的全部輸入。"""

from collections import defaultdict

from app.ingest.verify.baseline import Baseline
from app.ingest.verify.models import ArticleInput, Erratum, VerifySpec
from app.ingest.verify.profiles import CompanyProfile
from app.ingest.verify.textutil import normalize


class VerifyContext:
    def __init__(
        self,
        spec: VerifySpec,
        articles: list[ArticleInput],
        baseline: Baseline,
        profile: CompanyProfile,
        *,
        long_article_chars: int,
        errata: list[Erratum] | None = None,
    ) -> None:
        self.spec = spec
        # 依條號排序；排序是穩定的，重複條號維持輸入順序
        self.articles = sorted(articles, key=lambda a: a.article_no)
        self.baseline = baseline
        self.profile = profile
        self.long_article_chars = long_article_chars
        self.errata: dict[int, list[Erratum]] = defaultdict(list)
        for e in errata or []:
            self.errata[e.article_no].append(e)

    def neighbors(
        self, article: ArticleInput
    ) -> tuple[ArticleInput | None, ArticleInput | None]:
        i = next(i for i, a in enumerate(self.articles) if a is article)
        prev = self.articles[i - 1] if i > 0 else None
        nxt = self.articles[i + 1] if i + 1 < len(self.articles) else None
        return prev, nxt

    def with_errata(self, article_no: int, pdf_text: str) -> str | None:
        """把這一條的勘誤套到 PDF 原文（已正規化）上。沒有勘誤回傳 None。

        任何一筆的舊字在該條找不到或不只一處，整組勘誤就不算數（也回傳 None），
        PDF 換版後勘誤才不會悄悄失效。
        """
        errata = self.errata.get(article_no)
        if not errata:
            return None
        text = pdf_text
        for e in errata:
            old, new = normalize(e.old), normalize(e.new)
            if text.count(old) != 1:
                return None
            text = text.replace(old, new)
        return text

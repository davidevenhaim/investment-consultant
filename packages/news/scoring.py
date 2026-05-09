"""Deterministic news scoring — 0 to 15 points.

Algorithm:
  - No articles → 5.0 (conservative: no boost, no penalty)
  - With articles → base 7.5 + per-article contributions
  - Per-article max: +3.0 (positive) / -2.5 (negative)
  - Positive cap: 10.0 unless ≥3 independent positive signals → 12.5
"""

from news.schemas import NewsArticle, NewsScoreResult

_NO_DATA_SCORE: float = 5.0
_NEUTRAL_BASE: float = 7.5
_MAX_POSITIVE_PER_ARTICLE: float = 3.0
_MAX_NEGATIVE_PER_ARTICLE: float = -2.5
_CAP_FEW_POSITIVE: float = 10.0
_CAP_MANY_POSITIVE: float = 12.5
_POSITIVE_THRESHOLD: float = 0.1
_NEGATIVE_THRESHOLD: float = -0.1


def _article_contribution(article: NewsArticle) -> float:
    """Contribution of a single article. Capped at ±3.0/2.5."""
    combined = article.sentiment_score * article.importance_score * article.relevance_score
    if combined >= 0.0:
        return min(_MAX_POSITIVE_PER_ARTICLE, combined * _MAX_POSITIVE_PER_ARTICLE)
    return max(_MAX_NEGATIVE_PER_ARTICLE, combined * abs(_MAX_NEGATIVE_PER_ARTICLE))


def score_news_articles(articles: list[NewsArticle]) -> NewsScoreResult:
    """Score a list of news articles deterministically."""
    if not articles:
        return NewsScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason="No news data available. Conservative stub score applied.",
        )

    positive = [a for a in articles if a.sentiment_score > _POSITIVE_THRESHOLD]
    negative = [a for a in articles if a.sentiment_score < _NEGATIVE_THRESHOLD]
    neutral_count = len(articles) - len(positive) - len(negative)

    total_contribution = sum(_article_contribution(a) for a in articles)
    raw = _NEUTRAL_BASE + total_contribution

    cap_applied = False
    if raw > _CAP_FEW_POSITIVE:
        cap_applied = True
        raw = min(raw, _CAP_MANY_POSITIVE) if len(positive) >= 3 else _CAP_FEW_POSITIVE

    score = round(max(0.0, min(15.0, raw)), 2)

    # Build reason string
    parts: list[str] = [f"{len(articles)} article(s) analyzed."]
    if positive:
        parts.append(f"{len(positive)} positive.")
    if negative:
        parts.append(f"{len(negative)} negative.")
    if cap_applied:
        parts.append("Positive cap applied (insufficient independent signals).")

    # Top 5 articles by |contribution|
    top = sorted(articles, key=lambda a: abs(_article_contribution(a)), reverse=True)[:5]

    return NewsScoreResult(
        score=score,
        article_count=len(articles),
        positive_count=len(positive),
        negative_count=len(negative),
        neutral_count=neutral_count,
        positive_cap_applied=cap_applied,
        no_data=False,
        reason=" ".join(parts),
        top_articles=top,
    )

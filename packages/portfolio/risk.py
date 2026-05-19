"""Deterministic portfolio risk helpers — no LLM, no randomness."""

from db.enums import RecommendationAction

_BUY_ACTIONS = frozenset({"STRONG_BUY", "BUY_CANDIDATE"})
_REDUCE_ACTIONS = frozenset({"REDUCE", "SELL"})

_MAX_BY_RISK = {
    "LOW": 0.05,
    "MEDIUM": 0.08,
    "HIGH": 0.12,
}


def concentration_score(max_position_weight: float) -> float:
    """0.0 = perfectly diversified, 1.0 = fully concentrated."""
    return min(1.0, max(0.0, max_position_weight))


def classify_position_size(weight: float, max_single_stock_weight: float) -> str:
    """UNDERWEIGHT / NORMAL / OVERWEIGHT / NO_POSITION."""
    if weight <= 0:
        return "NO_POSITION"
    if weight < max_single_stock_weight * 0.5:
        return "UNDERWEIGHT"
    if weight <= max_single_stock_weight:
        return "NORMAL"
    return "OVERWEIGHT"


def recommended_position_size(
    risk_level: str,
    score: int,
    confidence: float,
    max_single_stock_weight: float,
) -> float:
    """Target weight for a new or expanded position. 0 if below gates."""
    if score < 70 or confidence < 0.65:
        return 0.0

    base_max = _MAX_BY_RISK.get(risk_level.upper(), _MAX_BY_RISK["MEDIUM"])
    cap = min(base_max, max_single_stock_weight)

    if confidence >= 0.85:
        scale = 1.0
    elif confidence >= 0.75:
        scale = 0.75
    elif confidence >= 0.65:
        scale = 0.50
    else:
        scale = 0.0

    return round(cap * scale, 4)


def portfolio_fit_score(
    current_weight: float,
    max_weight: float,
    cash_balance: float,
    total_equity: float,
    concentration: float,
    has_position: bool,
    neutral_action: str,
) -> float:
    """0–15 portfolio fit score (real, replaces stub).

    Components:
      diversification/concentration: 0–6
      room under max allocation:     0–5
      cash availability:             0–2
      current holding alignment:     0–2
    """
    score = 0.0

    # 1. Diversification (inverse of concentration): 0–6
    diversification = max(0.0, 1.0 - concentration)
    score += diversification * 6.0

    # 2. Room under max allocation: 0–5
    if max_weight > 0:
        remaining = max(0.0, max_weight - current_weight)
        room_pct = min(1.0, remaining / max_weight)
    else:
        room_pct = 0.0
    score += room_pct * 5.0

    # 3. Cash availability: 0–2
    if total_equity > 0:
        cash_pct = min(1.0, cash_balance / total_equity)
        score += cash_pct * 2.0
    else:
        score += 1.0  # unknown → neutral

    # 4. Holding alignment: 0–2
    is_buy = neutral_action in _BUY_ACTIONS
    is_reduce = neutral_action in _REDUCE_ACTIONS
    if not has_position and is_buy:
        score += 2.0  # no position + buy = perfect fit
    elif has_position and is_reduce:
        score += 2.0  # has position + reduce = aligned for trimming
    elif has_position and not is_buy and not is_reduce:
        score += 1.5  # has position + hold = aligned
    elif has_position and is_buy and current_weight < max_weight:
        score += 1.0  # has position but room remains
    # else: overweight + buy or no position + reduce → 0

    return round(min(15.0, max(0.0, score)), 2)


def build_trade_suggestion(
    personal_action: RecommendationAction,
    current_weight: float,
    target_weight: float,
    max_weight: float,
    total_equity: float,
) -> dict[str, object]:
    """Return suggested_trade_json dict."""
    is_buy = personal_action in (
        RecommendationAction.STRONG_BUY,
        RecommendationAction.BUY_CANDIDATE,
    )
    is_reduce = personal_action in (RecommendationAction.REDUCE, RecommendationAction.SELL)

    if is_buy and target_weight > current_weight and target_weight > 0:
        delta = target_weight - current_weight
        estimated = round(total_equity * delta, 2) if total_equity > 0 else None
        return {
            "trade_type": "BUY",
            "target_weight": round(target_weight, 4),
            "current_weight": round(current_weight, 4),
            "weight_delta": round(delta, 4),
            "estimated_amount": estimated,
            "rationale": [f"Build position to {target_weight:.0%} of portfolio."],
        }
    if is_reduce and current_weight > max_weight and max_weight > 0:
        delta = current_weight - max_weight
        estimated = round(total_equity * delta, 2) if total_equity > 0 else None
        return {
            "trade_type": "TRIM",
            "target_weight": round(max_weight, 4),
            "current_weight": round(current_weight, 4),
            "weight_delta": round(-delta, 4),
            "estimated_amount": estimated,
            "rationale": [f"Trim overweight from {current_weight:.0%} to {max_weight:.0%}."],
        }
    return {
        "trade_type": "NONE",
        "target_weight": round(target_weight, 4),
        "current_weight": round(current_weight, 4),
        "weight_delta": 0.0,
        "estimated_amount": None,
        "rationale": [],
    }

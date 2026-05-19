"""Pure helper functions for the replay quality report (M12.7).

No DB access, no LLM calls, no external I/O.
All functions accept and return plain Python dicts.
"""

from __future__ import annotations

from typing import Any


def build_report_point(
    run_id: str,
    as_of_date: str,
    neutral_action: str,
    neutral_score: int,
    personalized_action: str | None,
    price_at_recommendation: float | None,
    score_breakdown: dict[str, Any],
    missing_details: list[Any],
    created_at: str | None,
) -> dict[str, Any]:
    """Construct a single timeline point dict."""
    return {
        "run_id": run_id,
        "as_of_date": as_of_date,
        "neutral_action": neutral_action,
        "personalized_action": personalized_action,
        "neutral_score": neutral_score,
        "personalized_score": None,  # PersonalizedRecommendation has no numeric score field
        "price_at_recommendation": price_at_recommendation,
        "score_breakdown": score_breakdown,
        "missing_details": missing_details,
        "created_at": created_at,
    }


def _numeric_components(breakdown: dict[str, Any]) -> dict[str, float]:
    """Extract flat numeric (non-bool) fields from a score_breakdown_json dict."""
    return {
        k: float(v)
        for k, v in breakdown.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def build_timeline_changes(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute per-step change records for a sorted list of timeline points."""
    changes: list[dict[str, Any]] = []
    for i in range(1, len(points)):
        prev = points[i - 1]
        curr = points[i]

        prev_score: int | None = prev.get("neutral_score")
        curr_score: int | None = curr.get("neutral_score")
        neutral_delta: int | None = (
            (curr_score - prev_score) if prev_score is not None and curr_score is not None else None
        )

        action_changed = prev["neutral_action"] != curr["neutral_action"]

        prev_bd = _numeric_components(prev.get("score_breakdown") or {})
        curr_bd = _numeric_components(curr.get("score_breakdown") or {})
        changed_components: list[dict[str, Any]] = []
        for key in sorted(set(prev_bd) | set(curr_bd)):
            pv = prev_bd.get(key)
            cv = curr_bd.get(key)
            if pv is not None and cv is not None:
                delta = cv - pv
                if delta != 0:
                    changed_components.append(
                        {"key": key, "from": pv, "to": cv, "delta": round(delta, 4)}
                    )
        changed_components.sort(key=lambda x: abs(float(x["delta"])), reverse=True)

        explanation = _build_explanation(
            action_changed=action_changed,
            neutral_delta=neutral_delta,
            neutral_action_from=prev["neutral_action"],
            neutral_action_to=curr["neutral_action"],
            changed_components=changed_components,
        )

        changes.append(
            {
                "from_as_of_date": prev["as_of_date"],
                "to_as_of_date": curr["as_of_date"],
                "action_changed": action_changed,
                "neutral_action_from": prev["neutral_action"],
                "neutral_action_to": curr["neutral_action"],
                "personalized_action_from": prev.get("personalized_action"),
                "personalized_action_to": curr.get("personalized_action"),
                "neutral_score_delta": neutral_delta,
                "personalized_score_delta": None,
                "changed_components": changed_components,
                "explanation": explanation,
            }
        )
    return changes


def _build_explanation(
    *,
    action_changed: bool,
    neutral_delta: int | None,
    neutral_action_from: str,
    neutral_action_to: str,
    changed_components: list[dict[str, Any]],
) -> str:
    parts: list[str] = []
    if action_changed:
        parts.append(f"Action changed from {neutral_action_from} to {neutral_action_to}.")
    if neutral_delta is not None and neutral_delta != 0:
        direction = "increased" if neutral_delta > 0 else "decreased"
        parts.append(f"Score {direction} by {abs(neutral_delta)} points.")
    if changed_components:
        top = changed_components[0]
        direction = "improved" if float(top["delta"]) > 0 else "weakened"
        parts.append(
            f"Mainly because {top['key']} {direction} by {abs(float(top['delta'])):.1f} points."
        )
    if not parts:
        return "Recommendation remained broadly stable."
    return " ".join(parts)


def build_timeline_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate summary for a sorted list of timeline points."""
    if not points:
        return {
            "point_count": 0,
            "first_action": None,
            "last_action": None,
            "action_changed": False,
            "score_change": None,
            "max_score": None,
            "min_score": None,
            "largest_score_move": None,
        }

    scores: list[int] = [p["neutral_score"] for p in points if p.get("neutral_score") is not None]
    first_action: str | None = points[0]["neutral_action"]
    last_action: str | None = points[-1]["neutral_action"]

    score_change: int | None = (scores[-1] - scores[0]) if len(scores) >= 2 else None

    largest_score_move: dict[str, Any] | None = None
    if len(points) >= 2:
        max_abs: float = 0.0
        for i in range(1, len(points)):
            a = points[i - 1].get("neutral_score")
            b = points[i].get("neutral_score")
            if a is not None and b is not None:
                delta = b - a
                if abs(delta) > max_abs:
                    max_abs = abs(delta)
                    largest_score_move = {
                        "from_as_of_date": points[i - 1]["as_of_date"],
                        "to_as_of_date": points[i]["as_of_date"],
                        "delta": delta,
                    }

    return {
        "point_count": len(points),
        "first_action": first_action,
        "last_action": last_action,
        "action_changed": first_action != last_action,
        "score_change": score_change,
        "max_score": max(scores) if scores else None,
        "min_score": min(scores) if scores else None,
        "largest_score_move": largest_score_move,
    }

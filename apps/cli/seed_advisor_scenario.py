"""Dev-only scenario seeder for the advisor simulation engine (M11.2).

Seeds synthetic ResearchRun + ResearchRunTicker + NeutralRecommendation rows
so the advisor backtest has interesting trades to execute beyond boring HOLD recs.

Usage:
    python -m apps.cli.seed_advisor_scenario
    python -m apps.cli.seed_advisor_scenario --scenario mixed_buy_reduce_sell
    python -m apps.cli.seed_advisor_scenario --scenario bullish_rotation
    python -m apps.cli.seed_advisor_scenario --scenario risk_off
    python -m apps.cli.seed_advisor_scenario --user-id <uuid>
    python -m apps.cli.seed_advisor_scenario --reset
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import get_settings
from core.logging import get_logger, setup_logging
from db.session import get_session_factory, init_db

setup_logging()
logger = get_logger(__name__)

DEV_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Action → (score 0-100, confidence 0-1)
_ACTION_ATTRS: dict[str, tuple[int, float]] = {
    "STRONG_BUY": (88, 0.88),
    "BUY": (75, 0.75),
    "BUY_CANDIDATE": (72, 0.75),
    "HOLD": (55, 0.65),
    "REDUCE": (40, 0.60),
    "SELL": (25, 0.55),
    "NO_ACTION": (20, 0.50),
    "WATCHLIST": (48, 0.55),
}

# Approximate synthetic prices for seeded recs (display only, not used by simulation)
_APPROX_PRICES: dict[str, float] = {
    "AAPL": 185.0,
    "NVDA": 125.0,
    "AMD": 98.0,
    "TSLA": 245.0,
    "MSFT": 420.0,
    "GOOGL": 175.0,
}


@dataclass(frozen=True)
class ScenarioRec:
    date: dt.date
    symbol: str
    action: str  # RecommendationAction values + "BUY" (simulation handles it)


SCENARIOS: dict[str, list[ScenarioRec]] = {
    "mixed_buy_reduce_sell": [
        ScenarioRec(dt.date(2026, 1, 15), "AAPL", "BUY"),
        ScenarioRec(dt.date(2026, 2, 10), "NVDA", "BUY_CANDIDATE"),
        ScenarioRec(dt.date(2026, 3, 5), "AAPL", "HOLD"),
        ScenarioRec(dt.date(2026, 4, 1), "AMD", "STRONG_BUY"),
        ScenarioRec(dt.date(2026, 4, 20), "AAPL", "REDUCE"),
        ScenarioRec(dt.date(2026, 5, 1), "NVDA", "SELL"),
    ],
    "bullish_rotation": [
        ScenarioRec(dt.date(2026, 1, 10), "AAPL", "BUY"),
        ScenarioRec(dt.date(2026, 2, 1), "NVDA", "STRONG_BUY"),
        ScenarioRec(dt.date(2026, 3, 1), "AMD", "BUY_CANDIDATE"),
        ScenarioRec(dt.date(2026, 4, 15), "AAPL", "HOLD"),
    ],
    "risk_off": [
        ScenarioRec(dt.date(2026, 1, 10), "AAPL", "BUY"),
        ScenarioRec(dt.date(2026, 2, 15), "AAPL", "REDUCE"),
        ScenarioRec(dt.date(2026, 3, 15), "NVDA", "SELL"),
        ScenarioRec(dt.date(2026, 4, 1), "AMD", "NO_ACTION"),
    ],
}

DEFAULT_SCENARIO = "mixed_buy_reduce_sell"


def _score_breakdown(total: int, scenario_name: str) -> dict[str, Any]:
    ratio = total / 100.0
    return {
        "scenario": scenario_name,
        "scenario_seed": True,
        "total": total,
        "components": {
            "technical": round(20 * ratio),
            "fundamental": round(20 * ratio),
            "valuation": round(15 * ratio),
            "news": round(15 * ratio),
            "portfolio_fit": round(15 * ratio),
            "risk": round(15 * ratio),
        },
    }


async def warn_non_scenario_recommendations_in_window(
    session: Any,
    user_id: uuid.UUID,
    scenario_name: str,
) -> bool:
    """Print a warning when other (non-seeded) recs could affect the same simulation window.

    Returns True if a warning was printed.
    """
    from db.enums import ResearchRunStatus
    from db.models import NeutralRecommendation, ResearchRun
    from sqlalchemy import not_, select

    recs = SCENARIOS.get(scenario_name, [])
    if not recs:
        return False

    d_min = min(r.date for r in recs)
    d_max = max(r.date for r in recs)
    symbols = sorted({r.symbol.upper() for r in recs})

    seeded_marker = {"scenario_seed": True, "scenario": scenario_name}

    result = await session.execute(
        select(NeutralRecommendation.id)
        .join(ResearchRun, NeutralRecommendation.research_run_id == ResearchRun.id)
        .where(
            ResearchRun.user_id == user_id,
            ResearchRun.status == ResearchRunStatus.COMPLETED.value,
            ResearchRun.finished_at >= dt.datetime.combine(d_min, dt.time.min, tzinfo=dt.UTC),
            ResearchRun.finished_at <= dt.datetime.combine(d_max, dt.time.max, tzinfo=dt.UTC),
            NeutralRecommendation.symbol.in_(symbols),
            not_(ResearchRun.metadata_json.contains(seeded_marker)),
        )
        .limit(1)
    )
    if result.scalar_one_or_none() is None:
        return False

    print(
        "WARNING: Neutral recommendation(s) exist for this user on scenario symbols "
        f"{symbols} with research run finished_at between {d_min} and {d_max} that "
        f"are not '{scenario_name}' scenario_seed rows. Advisor simulation will "
        "include them and may duplicate or conflict with scenario trades.",
        file=sys.stderr,
    )
    return True


async def reset_scenario_for_user(
    session: Any,
    user_id: uuid.UUID,
    scenario_name: str,
) -> int:
    """Delete NeutralRecommendation + ResearchRun rows previously seeded for this scenario/user.

    Deletes NeutralRecommendation first (RESTRICT FK) then ResearchRun (tickers CASCADE).
    Returns number of runs deleted.
    """
    from db.models import NeutralRecommendation, ResearchRun
    from sqlalchemy import delete, select

    run_ids_result = await session.execute(
        select(ResearchRun.id).where(
            ResearchRun.user_id == user_id,
            ResearchRun.metadata_json.contains({"scenario_seed": True, "scenario": scenario_name}),
        )
    )
    run_ids = [row[0] for row in run_ids_result.fetchall()]
    if not run_ids:
        return 0

    await session.execute(
        delete(NeutralRecommendation).where(NeutralRecommendation.research_run_id.in_(run_ids))
    )
    await session.execute(delete(ResearchRun).where(ResearchRun.id.in_(run_ids)))
    await session.flush()
    return len(run_ids)


async def seed_scenario(
    session: Any,
    user_id: uuid.UUID,
    scenario_name: str,
) -> list[Any]:
    """Insert scenario rows and return the created NeutralRecommendation objects."""
    from db.enums import ResearchRunStatus, ResearchRunType, TickerRunStatus
    from db.models import NeutralRecommendation, ResearchRun, ResearchRunTicker
    from db.repositories import StrategyVersionRepository

    sv_repo = StrategyVersionRepository(session)
    strategy = await sv_repo.get_active()
    strategy_id = strategy.id if strategy else None
    if strategy is None:
        logger.warning(
            "seed_scenario_no_active_strategy",
            note="run 'make seed' first; strategy_version_id will be null",
        )

    recs = SCENARIOS[scenario_name]
    created: list[NeutralRecommendation] = []

    for rec in recs:
        rec_dt = dt.datetime.combine(rec.date, dt.time(10, 0), tzinfo=dt.UTC)
        score, confidence = _ACTION_ATTRS.get(rec.action, (50, 0.60))
        price = _APPROX_PRICES.get(rec.symbol.upper())

        run = ResearchRun(
            user_id=user_id,
            run_type=ResearchRunType.MANUAL.value,
            status=ResearchRunStatus.COMPLETED.value,
            strategy_version_id=strategy_id,
            started_at=rec_dt,
            finished_at=rec_dt,
            metadata_json={"scenario": scenario_name, "scenario_seed": True},
        )
        session.add(run)
        await session.flush()

        ticker = ResearchRunTicker(
            research_run_id=run.id,
            symbol=rec.symbol.upper(),
            status=TickerRunStatus.COMPLETED.value,
            started_at=rec_dt,
            finished_at=rec_dt,
        )
        session.add(ticker)
        await session.flush()

        nr = NeutralRecommendation(
            research_run_id=run.id,
            research_run_ticker_id=ticker.id,
            symbol=rec.symbol.upper(),
            action=rec.action,
            score=score,
            confidence=confidence,
            time_horizon="1M",
            score_breakdown_json=_score_breakdown(score, scenario_name),
            what_changed_json=[],
            main_reasons_json=[f"Scenario seed: {rec.action} on {rec.symbol.upper()}"],
            main_risks_json=[],
            missing_details_json=[],
            final_reason=(
                f"Score {score}/100 ({rec.action}). "
                f"Scenario seed ({scenario_name}): {rec.action} on {rec.symbol.upper()}."
            ),
            strategy_version_id=strategy_id,
            as_of_time=rec_dt,
            price_at_recommendation=price,
            data_quality_score=0.85,
        )
        nr.created_at = rec_dt
        session.add(nr)
        created.append(nr)

    await session.flush()
    return created


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    init_db(settings.database_url)
    factory = get_session_factory()

    user_id = DEV_DEFAULT_USER_ID
    if args.user_id:
        try:
            user_id = uuid.UUID(args.user_id)
        except ValueError:
            print(f"ERROR: invalid --user-id '{args.user_id}'", file=sys.stderr)
            sys.exit(1)

    scenario_name: str = args.scenario

    async with factory() as session:
        if args.reset:
            n_deleted = await reset_scenario_for_user(session, user_id, scenario_name)
            if n_deleted:
                print(
                    f"Reset: removed {n_deleted} previous '{scenario_name}'"
                    f" run(s) for user {user_id}."
                )
            else:
                print(f"Reset: no existing '{scenario_name}' rows found for user {user_id}.")
        else:
            print(
                f"WARNING: --reset not passed. Duplicate seeding may produce duplicate trades "
                f"in the simulation. Use --reset to replace previous '{scenario_name}' rows."
            )

        await warn_non_scenario_recommendations_in_window(session, user_id, scenario_name)

        created = await seed_scenario(session, user_id, scenario_name)
        await session.commit()

    print()
    print(f"Scenario : {scenario_name}")
    print(f"User     : {user_id}")
    print(f"Records  : {len(created)} neutral recommendation(s)")
    print()
    print(f"{'Date':<12} {'Symbol':<8} {'Action':<14} {'Score':>5}  {'Confidence':>10}")
    print("-" * 55)

    recs = SCENARIOS[scenario_name]
    for rec in recs:
        score, conf = _ACTION_ATTRS.get(rec.action, (50, 0.60))
        print(f"{rec.date!s:<12} {rec.symbol:<8} {rec.action:<14} {score:>5}  {conf:>10.2f}")

    print()
    print("Run advisor simulation:")
    print(
        "  curl -s -X POST http://localhost:8000/api/v1/backtesting/advisor-runs \\\n"
        '    -H "Content-Type: application/json" \\\n'
        "    -d '{"
        '"start_date":"2026-01-01","end_date":"2026-05-13",'
        '"initial_cash":10000,"benchmark_symbol":"SPY",'
        f'"name":"{scenario_name} simulation"'
        "}'"
        " | jq '.data | {status,final_equity,total_return_pct,total_trades,"
        "human_summary:.summary_json.human_summary}'"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed synthetic advisor scenario rows for backtest testing (dev only)."
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        choices=list(SCENARIOS),
        help=f"Scenario to seed (default: {DEFAULT_SCENARIO})",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help=f"Target user UUID (default: DEV_DEFAULT_USER_ID={DEV_DEFAULT_USER_ID})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete previous scenario rows for this user/scenario before inserting",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

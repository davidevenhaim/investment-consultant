"""Memory management CLI.

Commands:
    reset       — drop and recreate all Chroma collections (clears dev memory)
    list-failed — list FAILED memory_index_events from Postgres
    reindex     — reindex FAILED (or all) recommendations from Postgres into Chroma

Usage (inside Docker):
    docker compose exec api python -m apps.cli.memory reset
    docker compose exec api python -m apps.cli.memory list-failed
    docker compose exec api python -m apps.cli.memory reindex

Usage (local, outside Docker):
    PYTHONPATH=packages python apps/cli/memory.py reset
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))

from core.config import get_settings
from core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


# ── Adapters so build_recommendation_document can accept DB model fields ──────


class _ScoreBreakdownAdapter:
    def __init__(self, json: dict[str, Any]) -> None:
        self.technical_score: float = json.get("technical_score", 0.0)
        self.risk_score: float = json.get("risk_score", 0.0)
        self.fundamental_score: float = json.get("fundamental_score", 0.0)
        self.valuation_score: float = json.get("valuation_score", 0.0)
        self.news_score: float = json.get("news_score", 0.0)
        self.portfolio_fit_score: float = json.get("portfolio_fit_score", 0.0)
        self.total_score: float = json.get("total_score", 0.0)


class _ActionValue:
    def __init__(self, value: str) -> None:
        self.value = value


class _NeutralRecAdapter:
    def __init__(self, nr: Any) -> None:  # nr is NeutralRecommendation DB model
        self.action = _ActionValue(nr.action)
        self.score = nr.score
        self.confidence = nr.confidence
        self.score_breakdown = _ScoreBreakdownAdapter(nr.score_breakdown_json or {})
        self.main_reasons: list[str] = nr.main_reasons_json or []
        self.main_risks: list[str] = nr.main_risks_json or []
        self.missing_details: list[str] = nr.missing_details_json or []
        self.final_reason: str = nr.final_reason or ""


class _PersonalizedRecAdapter:
    def __init__(self, pr: Any) -> None:
        self.personal_action = _ActionValue(pr.personal_action)


# ── Commands ──────────────────────────────────────────────────────────────────


async def cmd_reset(force: bool = False) -> None:
    """
    Drop and recreate all Chroma collections. Permanently deletes all dev memory.
    Pass force=True (--yes / --force flag) to skip interactive confirmation.
    """
    from memory.chroma_client import make_chroma_store
    from memory.collections import ALL_COLLECTIONS

    print(f"Resetting Chroma collections: {ALL_COLLECTIONS}")
    print("WARNING: This permanently deletes all indexed research memory.")

    if not force:
        try:
            confirm = input("Type 'yes' to confirm: ").strip().lower()
        except EOFError:
            # Non-interactive context (piped stdin, make exec -T, CI).
            # Require --yes / --force flag explicitly.
            print("Non-interactive context detected. Re-run with --yes to confirm.")
            print("Example: make memory-reset-dev  (already passes --yes)")
            return
        if confirm != "yes":
            print("Aborted.")
            return

    store = make_chroma_store()
    await store.reset_collections()
    print("Done. All collections reset.")
    logger.info("memory_reset_complete", collections=ALL_COLLECTIONS)


async def cmd_list_failed() -> None:
    """List FAILED memory_index_events from Postgres."""

    from db.models import MemoryIndexEvent
    from db.session import get_session_factory, init_db
    from sqlalchemy import select

    settings = get_settings()
    init_db(settings.database_url)
    factory = get_session_factory()

    async with factory() as session:
        result = await session.execute(
            select(MemoryIndexEvent)
            .where(MemoryIndexEvent.status == "FAILED")
            .order_by(MemoryIndexEvent.created_at.desc())
        )
        events = result.scalars().all()

    if not events:
        print("No FAILED memory_index_events found.")
        return

    print(f"{'ID':<36}  {'Symbol':<6}  {'Chroma Doc ID':<50}  {'Created At'}")
    print("-" * 110)
    for e in events:
        print(
            f"{str(e.id):<36}  {(e.symbol or ''):<6}  "
            f"{(e.chroma_document_id or ''):<50}  {e.created_at}"
        )
    print(f"\nTotal: {len(events)} FAILED event(s).")


async def cmd_reindex(failed_only: bool = True) -> None:
    """
    Reindex recommendations from Postgres into Chroma.
    failed_only=True (default): only retry FAILED events.
    failed_only=False: reindex ALL neutral_recommendations.
    """

    from db.models import MemoryIndexEvent, NeutralRecommendation, PersonalizedRecommendation
    from db.session import get_session_factory, init_db
    from memory.chroma_client import make_chroma_store
    from memory.collections import RECOMMENDATION_REPORTS
    from memory.indexer import build_recommendation_document
    from sqlalchemy import select

    settings = get_settings()
    init_db(settings.database_url)
    factory = get_session_factory()
    store = make_chroma_store()

    async with factory() as session:
        if failed_only:
            # Find neutral_rec IDs from FAILED events
            evts_result = await session.execute(
                select(MemoryIndexEvent)
                .where(MemoryIndexEvent.status == "FAILED")
                .where(MemoryIndexEvent.entity_id.is_not(None))
            )
            events = evts_result.scalars().all()
            nr_ids = [e.entity_id for e in events if e.entity_id is not None]
            if not nr_ids:
                print("No FAILED events with entity_id found. Nothing to reindex.")
                return
            print(f"Reindexing {len(nr_ids)} failed recommendation(s)...")
            nr_result = await session.execute(
                select(NeutralRecommendation).where(NeutralRecommendation.id.in_(nr_ids))
            )
            recs = nr_result.scalars().all()
        else:
            print("Reindexing ALL neutral_recommendations...")
            nr_result = await session.execute(select(NeutralRecommendation))
            recs = nr_result.scalars().all()
            print(f"Found {len(recs)} recommendation(s).")

        indexed = 0
        failed = 0
        for nr in recs:
            # Find personalized rec (if any)
            pr_result = await session.execute(
                select(PersonalizedRecommendation).where(
                    PersonalizedRecommendation.neutral_recommendation_id == nr.id
                )
            )
            pr = pr_result.scalar_one_or_none()

            sv_id = str(nr.strategy_version_id) if nr.strategy_version_id else None
            price = float(nr.price_at_recommendation) if nr.price_at_recommendation else None

            try:
                doc = build_recommendation_document(
                    symbol=nr.symbol,
                    neutral_rec=_NeutralRecAdapter(nr),
                    personalized_rec=_PersonalizedRecAdapter(pr) if pr else None,
                    run_id=str(nr.research_run_id),
                    neutral_rec_id=str(nr.id),
                    personalized_rec_id=str(pr.id) if pr else None,
                    price_at_recommendation=price,
                    strategy_version_id=sv_id,
                )
                await store.add_document(RECOMMENDATION_REPORTS, doc)

                # Update FAILED events to INDEXED
                if failed_only:
                    for e in events:
                        if e.entity_id == nr.id:
                            e.status = "INDEXED"
                            e.error_message = None
                            e.chroma_document_id = doc.id

                await session.flush()
                indexed += 1
                print(f"  ✓ {nr.symbol} {nr.action} score={nr.score} → {doc.id}")
            except Exception as exc:
                failed += 1
                print(f"  ✗ {nr.symbol} {nr.id}: {exc}")

        await session.commit()

    print(f"\nReindex complete: {indexed} indexed, {failed} failed.")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]
    if cmd == "reset":
        force = "--yes" in args or "--force" in args
        asyncio.run(cmd_reset(force=force))
    elif cmd == "list-failed":
        asyncio.run(cmd_list_failed())
    elif cmd == "reindex":
        all_flag = "--all" in args
        asyncio.run(cmd_reindex(failed_only=not all_flag))
    else:
        print(f"Unknown command: {cmd}")
        print("Available commands: reset, list-failed, reindex [--all]")
        sys.exit(1)


if __name__ == "__main__":
    main()

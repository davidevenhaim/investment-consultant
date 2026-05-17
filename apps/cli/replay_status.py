"""CLI: print historical replay batch status.

Usage:
    python -m apps.cli.replay_status <replay_batch_id> [--user-id <uuid>]
"""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))

from core.config import get_settings
from db.session import get_session_factory, init_db


async def _print_batch_status(replay_batch_id: str, user_id: uuid.UUID) -> int:
    """Query and print replay batch status. Returns exit code."""
    from db.repositories import ResearchRunRepository

    settings = get_settings()
    init_db(settings.database_url)
    factory = get_session_factory()

    async with factory() as session:
        repo = ResearchRunRepository(session)
        runs = await repo.get_by_replay_batch_id(replay_batch_id, user_id)

    if not runs:
        print(f"ERROR: batch {replay_batch_id!r} not found for user {user_id}", file=sys.stderr)
        return 1

    counts: dict[str, int] = {}
    for r in runs:
        counts[r.status] = counts.get(r.status, 0) + 1

    terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
    terminal = sum(counts.get(s, 0) for s in terminal_statuses)
    total = len(runs)
    progress = round(terminal / total * 100, 1) if total else 0.0

    as_of_dates = [r.metadata_json.get("as_of_date", "?") for r in runs]

    print(f"replay_batch_id : {replay_batch_id}")
    print(f"total           : {total}")
    print(f"progress        : {progress}%  ({terminal}/{total} terminal)")
    print(f"status counts   : {counts}")
    print(f"date range      : {min(as_of_dates)} → {max(as_of_dates)}")
    print()
    print(f"{'as_of_date':<14}  {'status':<16}  id")
    print("-" * 60)
    for r in sorted(runs, key=lambda x: x.metadata_json.get("as_of_date", "")):
        aod = r.metadata_json.get("as_of_date", "?")
        print(f"{aod:<14}  {r.status:<16}  {r.id}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Print historical replay batch status.")
    parser.add_argument("replay_batch_id", help="The replay_batch_id UUID string.")
    parser.add_argument(
        "--user-id",
        default=None,
        help="User UUID (defaults to SCHEDULED_RESEARCH_USER_ID from config).",
    )
    args = parser.parse_args()

    if args.user_id:
        try:
            user_id = uuid.UUID(args.user_id)
        except ValueError:
            print(f"ERROR: invalid user-id: {args.user_id!r}", file=sys.stderr)
            sys.exit(1)
    else:
        settings = get_settings()
        user_id = uuid.UUID(settings.scheduled_research_user_id)

    exit_code = asyncio.run(_print_batch_status(args.replay_batch_id, user_id))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

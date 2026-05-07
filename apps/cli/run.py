"""CLI entry point to trigger a manual research run. Implemented fully in M3."""
import sys

from core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger(__name__)


def main() -> None:
    logger.info("manual_run_triggered", note="LangGraph graph implemented in M3")
    print("Research run trigger: implemented in Milestone 3.")
    sys.exit(0)


if __name__ == "__main__":
    main()

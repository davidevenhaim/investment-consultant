from celery import shared_task
from core.logging import get_logger

logger = get_logger(__name__)


@shared_task(
    name="apps.worker.tasks.research.run_scheduled_research",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def run_scheduled_research(self: object, run_type: str = "manual") -> dict[str, str]:
    """Trigger a full research run. Implemented in M3 (LangGraph graph)."""
    logger.info("research_run_triggered", run_type=run_type)
    return {"status": "queued", "run_type": run_type}

from celery import Celery
from celery.schedules import crontab
from core.config import get_settings
from core.logging import get_logger, setup_logging

settings = get_settings()
setup_logging(settings.log_level)

logger = get_logger(__name__)

celery_app = Celery(
    "investment_consultant",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["apps.worker.tasks.research"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
)


def _build_beat_schedule() -> dict[str, object]:
    """Build beat schedule from settings. Parses SCHEDULED_RESEARCH_HOURS as
    a comma-separated list of UTC hour integers (e.g. "9,16")."""
    try:
        hours = [int(h.strip()) for h in settings.scheduled_research_hours.split(",") if h.strip()]
    except ValueError:
        logger.warning(
            "scheduled_research_hours_invalid",
            value=settings.scheduled_research_hours,
        )
        hours = [9, 16]

    minute = settings.scheduled_research_minute
    schedule: dict[str, object] = {}
    labels = ["first", "second", "third", "fourth", "fifth"]
    for i, hour in enumerate(hours):
        label = labels[i] if i < len(labels) else str(i)
        schedule[f"scheduled-research-{label}"] = {
            "task": "apps.worker.tasks.research.scheduled_research_task",
            "schedule": crontab(hour=hour, minute=minute),
        }
    return schedule


celery_app.conf.beat_schedule = _build_beat_schedule()

# Alias for CLI invocation: celery -A apps.worker.celery_app worker
app = celery_app

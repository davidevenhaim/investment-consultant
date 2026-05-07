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
    beat_schedule={
        "morning-research-run": {
            "task": "apps.worker.tasks.research.run_scheduled_research",
            "schedule": crontab(hour=9, minute=0),
            "kwargs": {"run_type": "morning"},
        },
        "evening-research-run": {
            "task": "apps.worker.tasks.research.run_scheduled_research",
            "schedule": crontab(hour=16, minute=0),
            "kwargs": {"run_type": "evening"},
        },
    },
)

# Alias for CLI invocation: celery -A apps.worker.celery_app worker
app = celery_app

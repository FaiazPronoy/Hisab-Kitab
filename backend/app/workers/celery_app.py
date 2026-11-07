from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings
from app.core.logging import setup_logging

s = get_settings()
celery = Celery("docintel", broker=s.redis_url, backend=None, include=["app.workers.tasks"])
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_memory_per_child=600000,
    broker_transport_options={"visibility_timeout": 7200},
    task_default_queue="ingest",
    task_routes={
        "app.workers.tasks.ingest": {"queue": "ingest"},
        "app.workers.tasks.pages": {"queue": "ocr"},
        "app.workers.tasks.pages_heavy": {"queue": "ocr_heavy"},
        "app.workers.tasks.finalize": {"queue": "extract"},
        "app.workers.tasks.index": {"queue": "index"},
    },
    task_always_eager=s.celery_eager,
    task_eager_propagates=True,
    broker_connection_retry_on_startup=True,
)


@worker_process_init.connect
def _init(**_):
    setup_logging()

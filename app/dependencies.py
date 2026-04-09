"""
Shared FastAPI dependencies — queue provider, DB session, etc.
"""

from app.core.config import get_settings


# ── Queue singleton ──
_queue_instance = None


def get_queue():
    """
    Get the configured queue instance (MemoryQueue or SQSQueue).
    Lazy-initialized singleton based on QUEUE_BACKEND config.
    """
    global _queue_instance
    if _queue_instance is None:
        settings = get_settings()
        if settings.queue_backend == "sqs":
            from app.queue.sqs_client import SQSQueue
            _queue_instance = SQSQueue()
        else:
            from app.queue.memory_queue import MemoryQueue
            _queue_instance = MemoryQueue(max_retries=settings.max_retry_attempts)
    return _queue_instance


def reset_queue():
    """Reset queue singleton (used in tests)."""
    global _queue_instance
    _queue_instance = None

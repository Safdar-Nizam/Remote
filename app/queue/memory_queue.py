"""
In-memory queue implementation for local development and testing.
Implements the same interface as the SQS client so they are interchangeable.
"""

import asyncio
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class QueueMessage:
    """A message in the in-memory queue."""
    id: str
    body: dict
    receipt_handle: str
    enqueued_at: datetime
    attempt_count: int = 0


class MemoryQueue:
    """
    Async in-memory queue that mimics SQS behavior.
    Messages are stored in an asyncio.Queue.
    Failed messages go to a dead-letter list after max attempts.
    """

    def __init__(self, max_retries: int = 5):
        self._queue: asyncio.Queue[QueueMessage] = asyncio.Queue()
        self._dlq: list[QueueMessage] = []
        self._max_retries = max_retries
        self._processing = False

    async def send_message(self, body: dict, dedup_id: str | None = None) -> str:
        """Enqueue a message. Returns the message ID."""
        msg_id = dedup_id or str(uuid.uuid4())
        msg = QueueMessage(
            id=msg_id,
            body=body,
            receipt_handle=str(uuid.uuid4()),
            enqueued_at=datetime.now(timezone.utc),
        )
        await self._queue.put(msg)
        logger.debug("queue_send", message_id=msg_id, queue_size=self._queue.qsize())
        return msg_id

    async def receive_message(self, timeout: float = 1.0) -> QueueMessage | None:
        """Receive a single message from the queue. Returns None if empty after timeout."""
        try:
            msg = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            msg.attempt_count += 1
            return msg
        except asyncio.TimeoutError:
            return None

    async def delete_message(self, receipt_handle: str) -> None:
        """Acknowledge successful processing (no-op for in-memory, message already dequeued)."""
        logger.debug("queue_delete", receipt_handle=receipt_handle)

    async def nack_message(self, msg: QueueMessage) -> None:
        """Return a failed message to the queue, or send to DLQ if max retries exceeded."""
        if msg.attempt_count >= self._max_retries:
            self._dlq.append(msg)
            logger.warning("queue_to_dlq", message_id=msg.id, attempts=msg.attempt_count)
        else:
            await self._queue.put(msg)
            logger.info("queue_requeue", message_id=msg.id, attempt=msg.attempt_count)

    def dlq_depth(self) -> int:
        return len(self._dlq)

    def queue_depth(self) -> int:
        return self._queue.qsize()

    def get_dlq_messages(self) -> list[QueueMessage]:
        return list(self._dlq)

    async def start_consumer(self, handler: Callable, poll_interval: float = 0.5) -> None:
        """Start consuming messages in a background loop."""
        self._processing = True
        logger.info("queue_consumer_started")
        while self._processing:
            msg = await self.receive_message(timeout=poll_interval)
            if msg:
                try:
                    await handler(msg.body)
                    await self.delete_message(msg.receipt_handle)
                except Exception as e:
                    logger.error("queue_handler_error", message_id=msg.id, error=str(e))
                    await self.nack_message(msg)

    def stop_consumer(self) -> None:
        """Signal the consumer loop to stop."""
        self._processing = False
        logger.info("queue_consumer_stopped")

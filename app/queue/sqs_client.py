"""
SQS queue client — production queue backend using AWS SQS.
Same interface as MemoryQueue for seamless swapping via config.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Callable

import boto3

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SQSMessage:
    id: str
    body: dict
    receipt_handle: str
    enqueued_at: datetime
    attempt_count: int = 0


class SQSQueue:
    """
    AWS SQS queue client.
    Uses boto3 synchronously (called from async context via run_in_executor if needed).
    """

    def __init__(self):
        settings = get_settings()
        self._sqs = boto3.client("sqs", region_name=settings.aws_region)
        self._queue_url = settings.sqs_queue_url
        self._dlq_url = settings.sqs_dlq_url

    async def send_message(self, body: dict, dedup_id: str | None = None) -> str:
        """Send a message to the SQS queue."""
        msg_id = dedup_id or str(uuid.uuid4())
        response = self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(body),
            MessageGroupId="onboarding",  # For FIFO queues
            MessageDeduplicationId=msg_id,
        )
        logger.info("sqs_sent", message_id=response.get("MessageId", msg_id))
        return response.get("MessageId", msg_id)

    async def receive_message(self, timeout: float = 1.0) -> SQSMessage | None:
        """Receive a single message from SQS."""
        response = self._sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=int(timeout),
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        if not messages:
            return None

        raw = messages[0]
        return SQSMessage(
            id=raw["MessageId"],
            body=json.loads(raw["Body"]),
            receipt_handle=raw["ReceiptHandle"],
            enqueued_at=datetime.now(timezone.utc),
            attempt_count=int(raw.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
        )

    async def delete_message(self, receipt_handle: str) -> None:
        """Delete (acknowledge) a processed message."""
        self._sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle)

    async def nack_message(self, msg: SQSMessage) -> None:
        """Make message visible again by setting visibility timeout to 0."""
        self._sqs.change_message_visibility(
            QueueUrl=self._queue_url,
            ReceiptHandle=msg.receipt_handle,
            VisibilityTimeout=0,
        )

    def dlq_depth(self) -> int:
        if not self._dlq_url:
            return 0
        attrs = self._sqs.get_queue_attributes(
            QueueUrl=self._dlq_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(attrs["Attributes"].get("ApproximateNumberOfMessages", 0))

    async def start_consumer(self, handler: Callable, poll_interval: float = 1.0) -> None:
        """Long-poll consumer loop for SQS."""
        import asyncio
        self._processing = True
        logger.info("sqs_consumer_started")
        while self._processing:
            msg = await self.receive_message(timeout=poll_interval)
            if msg:
                try:
                    await handler(msg.body)
                    await self.delete_message(msg.receipt_handle)
                except Exception as e:
                    logger.error("sqs_handler_error", message_id=msg.id, error=str(e))
                    # SQS will auto-retry via visibility timeout / redrive policy

    def stop_consumer(self) -> None:
        self._processing = False

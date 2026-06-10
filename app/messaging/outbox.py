import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from faststream.rabbit import RabbitBroker
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.messaging.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_NEW_ROUTING_KEY,
)
from app.models.outbox import OutboxEvent, OutboxStatus

logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(
        self,
        broker: RabbitBroker,
        session_factory: async_sessionmaker,
        *,
        poll_interval_seconds: float,
        batch_size: int,
        retention_seconds: float,
        cleanup_interval_seconds: float,
    ) -> None:
        self._broker = broker
        self._session_factory = session_factory
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._retention_seconds = retention_seconds
        self._cleanup_interval_seconds = cleanup_interval_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="outbox-publisher")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        next_cleanup = 0.0
        while True:
            try:
                await self.publish_once()
            except Exception:
                logger.exception("Outbox publisher iteration failed")
            if time.monotonic() >= next_cleanup:
                try:
                    await self.purge_published()
                except Exception:
                    logger.exception("Outbox cleanup failed")
                next_cleanup = time.monotonic() + self._cleanup_interval_seconds
            await asyncio.sleep(self._poll_interval_seconds)

    async def publish_once(self) -> int:
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.status == OutboxStatus.PENDING.value)
                    .order_by(OutboxEvent.created_at)
                    .limit(self._batch_size)
                    .with_for_update(skip_locked=True),
                )
                events = list(result.scalars())

                for event in events:
                    try:
                        await self._broker.publish(
                            event.payload,
                            queue=PAYMENTS_NEW_QUEUE,
                            exchange=PAYMENTS_EXCHANGE,
                            routing_key=PAYMENTS_NEW_ROUTING_KEY,
                            persist=True,
                            message_id=str(event.id),
                            message_type=event.event_type,
                        )
                    except Exception as exc:
                        event.attempts += 1
                        event.last_error = str(exc)[:2000]
                        logger.warning(
                            "Failed to publish outbox event %s on attempt %s: %s",
                            event.id,
                            event.attempts,
                            exc,
                        )
                    else:
                        event.status = OutboxStatus.PUBLISHED.value
                        event.published_at = datetime.now(UTC)
                        event.last_error = None

        return len(events)

    async def purge_published(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=self._retention_seconds)
        async with self._session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(OutboxEvent).where(
                        OutboxEvent.status == OutboxStatus.PUBLISHED.value,
                        OutboxEvent.published_at < cutoff,
                    ),
                )
        if result.rowcount:
            logger.info("Purged %s published outbox events", result.rowcount)
        return result.rowcount

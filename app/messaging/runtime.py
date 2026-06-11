from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from faststream.rabbit import RabbitBroker

from app.core.config import settings
from app.db.session import async_session_maker
from app.messaging.outbox import OutboxPublisher
from app.messaging.topology import declare_topology


@asynccontextmanager
async def outbox_runtime() -> AsyncIterator[tuple[RabbitBroker, OutboxPublisher]]:
    broker = RabbitBroker(settings.rabbitmq_url)
    await broker.start()
    await declare_topology(broker)

    outbox = OutboxPublisher(
        broker,
        async_session_maker,
        poll_interval_seconds=settings.outbox_poll_interval_seconds,
        batch_size=settings.outbox_batch_size,
        retention_seconds=settings.outbox_retention_seconds,
        cleanup_interval_seconds=settings.outbox_cleanup_interval_seconds,
    )
    outbox.start()

    try:
        yield broker, outbox
    finally:
        await outbox.stop()
        await broker.stop()

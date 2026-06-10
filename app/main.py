import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker

from app.api.routes import router
from app.core.config import settings
from app.db.session import async_session_maker
from app.messaging.outbox import OutboxPublisher
from app.messaging.topology import declare_topology

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    broker = RabbitBroker(settings.rabbitmq_url)
    await broker.start()
    await declare_topology(broker)

    outbox = OutboxPublisher(
        broker,
        async_session_maker,
        poll_interval_seconds=settings.outbox_poll_interval_seconds,
        batch_size=settings.outbox_batch_size,
        max_publish_attempts=settings.outbox_max_publish_attempts,
        retention_seconds=settings.outbox_retention_seconds,
        cleanup_interval_seconds=settings.outbox_cleanup_interval_seconds,
    )
    outbox.start()
    app.state.broker = broker
    app.state.outbox = outbox

    try:
        yield
    finally:
        await outbox.stop()
        await broker.stop()


app = FastAPI(title="Async Payment Processor", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}

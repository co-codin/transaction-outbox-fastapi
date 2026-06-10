import logging

from faststream import FastStream
from faststream.rabbit import Channel, RabbitBroker

from app.core.config import settings
from app.messaging.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    WEBHOOKS_EXCHANGE,
    WEBHOOKS_QUEUE,
    declare_topology,
)
from app.schemas.messages import PaymentEvent, WebhookDeliveryEvent
from app.services.processor import process_payment_event
from app.services.webhooks import process_webhook_event

logging.basicConfig(level=logging.INFO)

broker = RabbitBroker(settings.rabbitmq_url)
app = FastStream(broker)


@app.after_startup
async def setup_topology() -> None:
    await declare_topology(broker)


@broker.subscriber(
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_EXCHANGE,
    channel=Channel(prefetch_count=settings.consumer_prefetch_count),
)
async def handle_payment(event: PaymentEvent) -> None:
    await process_payment_event(event, broker)


@broker.subscriber(
    WEBHOOKS_QUEUE,
    WEBHOOKS_EXCHANGE,
    channel=Channel(prefetch_count=settings.consumer_prefetch_count),
)
async def handle_webhook(event: WebhookDeliveryEvent) -> None:
    await process_webhook_event(event, broker)

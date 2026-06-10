import pytest

from app.messaging.topology import (
    PAYMENTS_EXCHANGE,
    PAYMENTS_NEW_QUEUE,
    PAYMENTS_NEW_ROUTING_KEY,
    PAYMENTS_RETRY_QUEUES,
    WEBHOOKS_EXCHANGE,
    WEBHOOKS_QUEUE,
    WEBHOOKS_RETRY_QUEUES,
    WEBHOOKS_ROUTING_KEY,
    route_for_event_type,
)
from app.schemas.messages import PAYMENT_CREATED_EVENT_TYPE, WEBHOOK_DELIVERY_EVENT_TYPE


def test_payments_queue_declares_dead_letter_routing() -> None:
    assert PAYMENTS_NEW_QUEUE.arguments["x-dead-letter-exchange"] == "payments.dead"
    assert PAYMENTS_NEW_QUEUE.arguments["x-dead-letter-routing-key"] == "payments.dlq"


def test_retry_queues_use_exponential_ttl_backoff() -> None:
    assert [queue.arguments["x-message-ttl"] for queue in PAYMENTS_RETRY_QUEUES] == [
        2000,
        4000,
    ]
    assert all(
        queue.arguments["x-dead-letter-exchange"] == "payments"
        and queue.arguments["x-dead-letter-routing-key"] == "payments.new"
        for queue in PAYMENTS_RETRY_QUEUES
    )


def test_webhook_queue_declares_dead_letter_routing() -> None:
    assert WEBHOOKS_QUEUE.arguments["x-dead-letter-exchange"] == "webhooks.dead"
    assert WEBHOOKS_QUEUE.arguments["x-dead-letter-routing-key"] == "webhooks.dlq"


def test_webhook_retry_queues_use_exponential_ttl_backoff() -> None:
    assert [queue.arguments["x-message-ttl"] for queue in WEBHOOKS_RETRY_QUEUES] == [
        2000,
        4000,
    ]
    assert all(
        queue.arguments["x-dead-letter-exchange"] == "webhooks"
        and queue.arguments["x-dead-letter-routing-key"] == "webhooks.deliver"
        for queue in WEBHOOKS_RETRY_QUEUES
    )


def test_outbox_routes_payment_and_webhook_events() -> None:
    payment_route = route_for_event_type(PAYMENT_CREATED_EVENT_TYPE)
    webhook_route = route_for_event_type(WEBHOOK_DELIVERY_EVENT_TYPE)

    assert payment_route.exchange == PAYMENTS_EXCHANGE
    assert payment_route.queue == PAYMENTS_NEW_QUEUE
    assert payment_route.routing_key == PAYMENTS_NEW_ROUTING_KEY
    assert webhook_route.exchange == WEBHOOKS_EXCHANGE
    assert webhook_route.queue == WEBHOOKS_QUEUE
    assert webhook_route.routing_key == WEBHOOKS_ROUTING_KEY


def test_outbox_route_rejects_unknown_event_type() -> None:
    with pytest.raises(ValueError, match="Unsupported outbox event type"):
        route_for_event_type("unknown.event")

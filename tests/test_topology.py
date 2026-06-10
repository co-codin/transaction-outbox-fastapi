from app.messaging.topology import PAYMENTS_NEW_QUEUE, PAYMENTS_RETRY_QUEUES


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

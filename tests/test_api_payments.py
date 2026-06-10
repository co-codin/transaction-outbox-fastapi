from uuid import uuid4

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_create_payment_requires_api_key(client: AsyncClient) -> None:
    response = await client.post("/api/v1/payments", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key"


async def test_create_payment_requires_idempotency_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/payments",
        headers=auth_headers,
        json={
            "amount": "1500.00",
            "currency": "RUB",
            "description": "Order smoke test",
            "metadata": {"order_id": "smoke-1"},
            "webhook_url": "https://example.com/webhook",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"


async def test_create_payment_rejects_blank_idempotency_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/payments",
        headers={**auth_headers, "Idempotency-Key": "   "},
        json={
            "amount": "1500.00",
            "currency": "RUB",
            "description": "Order smoke test",
            "metadata": {"order_id": "smoke-1"},
            "webhook_url": "https://example.com/webhook",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Idempotency-Key header is required"


async def test_create_payment_rejects_oversized_idempotency_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/payments",
        headers={**auth_headers, "Idempotency-Key": "k" * 256},
        json={
            "amount": "1500.00",
            "currency": "RUB",
            "description": "Order smoke test",
            "metadata": {"order_id": "smoke-1"},
            "webhook_url": "https://example.com/webhook",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Idempotency-Key header must be at most 255 characters"
    )


async def test_create_payment_strips_idempotency_key(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/payments",
        headers={**auth_headers, "Idempotency-Key": "  smoke-1  "},
        json={
            "amount": "1500.00",
            "currency": "RUB",
            "description": "Order smoke test",
            "metadata": {"order_id": "smoke-1"},
            "webhook_url": "https://example.com/webhook",
        },
    )

    assert response.status_code == 202

    detail = await client.get(
        f"/api/v1/payments/{response.json()['payment_id']}",
        headers=auth_headers,
    )
    assert detail.json()["idempotency_key"] == "smoke-1"


async def test_create_payment_returns_accepted_payment(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/payments",
        headers={**auth_headers, "Idempotency-Key": "smoke-1"},
        json={
            "amount": "1500.00",
            "currency": "RUB",
            "description": "Order smoke test",
            "metadata": {"order_id": "smoke-1"},
            "webhook_url": "https://example.com/webhook",
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
        "status": "pending",
        "created_at": "2026-06-10T14:53:49Z",
    }


async def test_get_payment_returns_detail(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get(
        "/api/v1/payments/a1163e5d-8f5e-432b-96dd-48ff68204948",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "payment_id": "a1163e5d-8f5e-432b-96dd-48ff68204948",
        "amount": "1500.00",
        "currency": "RUB",
        "description": "Order smoke test",
        "metadata": {"order_id": "smoke-1"},
        "status": "pending",
        "idempotency_key": "smoke-1",
        "webhook_url": "https://example.com/webhook",
        "created_at": "2026-06-10T14:53:49Z",
        "processed_at": None,
    }


async def test_get_payment_returns_404(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    response = await client.get(f"/api/v1/payments/{uuid4()}", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Payment not found"

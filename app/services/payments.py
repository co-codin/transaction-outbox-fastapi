import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.payment import Payment, PaymentStatus
from app.schemas.messages import PAYMENT_CREATED_EVENT_TYPE, PaymentEvent
from app.schemas.payments import PaymentCreate


class IdempotencyKeyConflictError(Exception):
    pass


def _matches_payload(payment: Payment, payload: PaymentCreate) -> bool:
    return (
        payment.amount == payload.amount
        and payment.currency == payload.currency
        and payment.description == payload.description
        and payment.metadata_ == payload.metadata
        and payment.webhook_url == str(payload.webhook_url)
    )


def _existing_or_conflict(payment: Payment, payload: PaymentCreate) -> Payment:
    if not _matches_payload(payment, payload):
        raise IdempotencyKeyConflictError(payment.idempotency_key)
    return payment


async def create_payment(
    session: AsyncSession,
    payload: PaymentCreate,
    idempotency_key: str,
) -> Payment:
    existing = await get_payment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return _existing_or_conflict(existing, payload)

    payment = Payment(
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata_=payload.metadata,
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        webhook_url=str(payload.webhook_url),
    )
    session.add(payment)
    await session.flush()

    session.add(
        OutboxEvent(
            aggregate_id=payment.id,
            event_type=PAYMENT_CREATED_EVENT_TYPE,
            payload=PaymentEvent(payment_id=payment.id).model_dump(mode="json"),
        ),
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_payment_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return _existing_or_conflict(existing, payload)
        raise

    await session.refresh(payment)
    return payment


async def get_payment(session: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    return await session.get(Payment, payment_id)


async def get_payment_by_idempotency_key(
    session: AsyncSession,
    idempotency_key: str,
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.idempotency_key == idempotency_key),
    )
    return result.scalar_one_or_none()

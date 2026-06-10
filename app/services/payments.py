import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent
from app.models.payment import Payment, PaymentStatus
from app.schemas.payments import PaymentCreate


async def create_payment(
    session: AsyncSession,
    payload: PaymentCreate,
    idempotency_key: str,
) -> Payment:
    existing = await get_payment_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        return existing

    payment = Payment(
        amount=payload.amount,
        currency=payload.currency.value,
        description=payload.description,
        metadata_=payload.metadata,
        status=PaymentStatus.PENDING.value,
        idempotency_key=idempotency_key,
        webhook_url=str(payload.webhook_url),
    )
    session.add(payment)
    await session.flush()

    session.add(
        OutboxEvent(
            aggregate_id=payment.id,
            event_type="payment.created",
            payload={"payment_id": str(payment.id), "attempt": 1},
        ),
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await get_payment_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return existing
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

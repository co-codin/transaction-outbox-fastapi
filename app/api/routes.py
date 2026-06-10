import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import ApiKeyDep, SessionDep
from app.schemas.payments import PaymentAccepted, PaymentCreate, PaymentDetail, accepted_from_model
from app.services.payments import create_payment, get_payment

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.post(
    "/payments",
    response_model=PaymentAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_payment_endpoint(
    _: ApiKeyDep,
    payload: PaymentCreate,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> PaymentAccepted:
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )

    payment = await create_payment(session, payload, idempotency_key)
    return accepted_from_model(payment)


@router.get("/payments/{payment_id}", response_model=PaymentDetail)
async def get_payment_endpoint(
    _: ApiKeyDep,
    payment_id: uuid.UUID,
    session: SessionDep,
) -> PaymentDetail:
    payment = await get_payment(session, payment_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    return PaymentDetail.from_model(payment)

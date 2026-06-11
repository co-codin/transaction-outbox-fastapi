import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import ApiKeyDep, SessionDep
from app.schemas.payments import PaymentAccepted, PaymentCreate, PaymentDetail
from app.services.idempotency import (
    IdempotencyKeyValidationError,
    normalize_idempotency_key,
)
from app.services.payments import IdempotencyKeyConflictError, create_payment, get_payment

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
    try:
        idempotency_key = normalize_idempotency_key(idempotency_key)
    except IdempotencyKeyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from None

    try:
        payment = await create_payment(session, payload, idempotency_key)
    except IdempotencyKeyConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key already used with a different request body",
        ) from None
    return PaymentAccepted.model_validate(payment)


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
    return PaymentDetail.model_validate(payment)

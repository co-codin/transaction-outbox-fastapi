import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import ApiKeyDep, SessionDep
from app.schemas.payments import PaymentAccepted, PaymentCreate, PaymentDetail, accepted_from_model
from app.services.payments import create_payment, get_payment

router = APIRouter(prefix="/api/v1", tags=["payments"])

# Must match the payments.idempotency_key column: String(255).
IDEMPOTENCY_KEY_MAX_LENGTH = 255


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
    idempotency_key = (idempotency_key or "").strip()
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    if len(idempotency_key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Idempotency-Key header must be at most "
                f"{IDEMPOTENCY_KEY_MAX_LENGTH} characters"
            ),
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

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from app.api.deps import ApiKeyDep, SessionDep
from app.schemas.payments import PaymentAccepted, PaymentCreate, PaymentDetail
from app.services.payments import IdempotencyKeyConflictError, create_payment, get_payment

router = APIRouter(prefix="/api/v1", tags=["payments"])

# Must match the payments.idempotency_key column (String(255)); a longer value
# would otherwise fail at INSERT with StringDataRightTruncation (an unhandled 500)
# instead of a clean 400.
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

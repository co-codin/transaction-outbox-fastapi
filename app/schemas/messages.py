import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.payment import Currency, PaymentStatus

PAYMENT_CREATED_EVENT_TYPE = "payments.new"


class PaymentEvent(BaseModel):
    payment_id: uuid.UUID
    attempt: int = Field(default=1, ge=1)


class WebhookPayload(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    event: Literal["payment.processed"] = "payment.processed"
    payment_id: uuid.UUID = Field(validation_alias="id")
    status: PaymentStatus
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    processed_at: datetime | None

    @field_serializer("amount")
    def _amount_as_plain_string(self, value: Decimal) -> str:
        return format(value, "f")

    @field_serializer("created_at", "processed_at")
    def _datetime_with_offset(self, value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

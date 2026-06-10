import uuid

from pydantic import BaseModel, Field


class PaymentEvent(BaseModel):
    payment_id: uuid.UUID
    attempt: int = Field(default=1, ge=1)

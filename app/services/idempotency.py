IDEMPOTENCY_KEY_MAX_LENGTH = 255


class IdempotencyKeyValidationError(ValueError):
    pass


def normalize_idempotency_key(value: str | None) -> str:
    idempotency_key = (value or "").strip()
    if not idempotency_key:
        raise IdempotencyKeyValidationError("Idempotency-Key header is required")
    if len(idempotency_key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise IdempotencyKeyValidationError(
            "Idempotency-Key header must be at most "
            f"{IDEMPOTENCY_KEY_MAX_LENGTH} characters",
        )
    return idempotency_key

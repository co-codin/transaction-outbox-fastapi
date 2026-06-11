import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.messaging.runtime import outbox_runtime

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with outbox_runtime() as (broker, outbox):
        app.state.broker = broker
        app.state.outbox = outbox
        yield


app = FastAPI(title="Async Payment Processor", version="1.0.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}

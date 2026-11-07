"""Fictional application, used only in reproducible integration demonstrations."""

import os
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException

from .client import SentinelClient, SentinelUnavailable
from .models import Event

USERS = {
    "demo-a": {"id": "opaque-user-a", "tenant": "company-a"},
    "demo-b": {"id": "opaque-user-b", "tenant": "company-b"},
}
DOCUMENTS = {
    "a": {"tenant": "company-a", "text": "Fictional A document"},
    "b": {"tenant": "company-b", "text": "Fictional B document"},
}


def create_documents_app(sentinel_url=None, collector_key=None, timeout=2):
    @asynccontextmanager
    async def lifespan(app):
        with SentinelClient(
            sentinel_url or os.environ["SENTINEL_URL"],
            collector_key or os.environ["SENTINEL_COLLECTOR_KEY"],
            timeout=timeout,
        ) as guard:
            app.state.guard = guard
            yield

    app = FastAPI(title="Fictional documents integration", lifespan=lifespan)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/documents/{document_id}")
    def document(document_id: str, authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Demonstration bearer identity required")
        user = USERS.get(authorization[7:])
        if not user:
            raise HTTPException(401, "Unknown demonstration identity")
        resource = DOCUMENTS.get(document_id)
        if not resource:
            raise HTTPException(404)
        try:
            decision = app.state.guard.decide(
                Event(
                    service="documents",
                    route="/documents/{id}",
                    subject=user["id"],
                    actor_tenant=user["tenant"],
                    resource_tenant=resource["tenant"],
                )
            )
        except SentinelUnavailable as exc:
            raise HTTPException(503, "Policy service unavailable") from exc
        if not decision["allowed"]:
            raise HTTPException(403, "Policy denied access")
        if user["tenant"] != resource["tenant"]:
            raise HTTPException(403, "Application authorization denied access")
        return {"text": resource["text"]}

    return app

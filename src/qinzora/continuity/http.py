"""FastAPI management adapter; the runtime remains framework-independent."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ..errors import ApplicationError, require
from ..models import Model
from ..repository import account_transaction
from ..store import Store
from .contracts import FallbackProfile, OperationContract, Rehearsal
from .service import (
    activate_profile,
    activation_digest,
    create_contract,
    create_profile,
    inspect_profile,
    revoke_profile,
    set_rehearsal,
)


class ActivationRequest(Model):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledge_impact: bool = False


def create_router(store: Store, manager: Callable) -> APIRouter:
    router = APIRouter(prefix="/v1/continuity", tags=["continuity"])
    Manager = Annotated[dict, Depends(manager)]

    @router.post("/contracts", status_code=201)
    def register_contract(body: OperationContract, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            return create_contract(repository, body)

    @router.get("/contracts/{contract_id}")
    def get_contract(contract_id: str, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            return {
                "id": contract_id,
                **require(repository.get("continuity_contract", contract_id)),
            }

    @router.post("/profiles", status_code=201)
    def register_profile(body: FallbackProfile, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            return create_profile(repository, body)

    @router.get("/profiles")
    def list_profiles(
        identity: Manager, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ):
        with account_transaction(store, identity["tenant"]) as repository:
            return Store.listing(
                repository.db, identity["tenant"], "continuity_profile", limit, offset
            )

    @router.get("/profiles/{profile_id}")
    def get_profile(profile_id: str, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            return inspect_profile(repository, profile_id)

    @router.put("/profiles/{profile_id}/rehearsal")
    def update_rehearsal(profile_id: str, body: Rehearsal, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            set_rehearsal(repository, profile_id, body)
            return inspect_profile(repository, profile_id)

    @router.post("/profiles/{profile_id}/simulate")
    def simulate_profile(profile_id: str, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            item = inspect_profile(repository, profile_id)
            signature = activation_digest(item)
            repository.audit(
                "continuity.simulated", {"profile_id": profile_id, "digest": signature}
            )
            return {"profile_id": profile_id, "config_digest": signature, **item["report"]}

    @router.post("/profiles/{profile_id}/activate")
    def enable_profile(profile_id: str, body: ActivationRequest, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            item = inspect_profile(repository, profile_id)
            if not body.acknowledge_impact or body.expected_digest != activation_digest(item):
                raise ApplicationError(
                    "conflict", "Review current continuity rehearsal and acknowledge impact"
                )
            return activate_profile(
                repository, profile_id, maximum_ttl=86400, maximum_evidence_age=900
            )

    @router.post("/profiles/{profile_id}/revoke")
    def disable_profile(profile_id: str, identity: Manager):
        with account_transaction(store, identity["tenant"]) as repository:
            return revoke_profile(repository, profile_id)

    return router

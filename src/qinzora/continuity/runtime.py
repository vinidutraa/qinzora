"""Run registered read fallbacks only after request-time contract checks."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ..errors import ApplicationError, require
from ..models import now
from ..ports import RepositoryFactory
from .contracts import OperationContract, SnapshotEvidence
from .engine import evaluate_rules, violations
from .service import activation_digest, record_health, resolve_profile


class DependencyUnavailable(RuntimeError):
    """An adapter reports a dependency outage, not an authorization/application error."""


class ContinuityUnavailable(RuntimeError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("No permitted API response is available")


@dataclass(frozen=True)
class VerifiedCall:
    consumer: str
    actor_tenant: str | None
    resource_tenant: str | None
    authorized: bool = False


@dataclass(frozen=True)
class CachedResponse:
    data: Mapping[str, Any]
    generated_at: datetime
    consumer: str
    resource_tenant: str


@dataclass(frozen=True)
class ContinuityResponse:
    data: dict[str, Any]
    source: Literal["primary", "cache"]
    profile_id: str | None = None
    age_seconds: float | None = None


SnapshotLoader = Callable[[str, VerifiedCall], Awaitable[CachedResponse | None]]


class ContinuityRuntime:
    def __init__(
        self,
        repository: RepositoryFactory,
        sources: Mapping[str, SnapshotLoader],
        *,
        timeout: float = 2,
    ):
        if not 0 < timeout <= 300:
            raise ValueError("Continuity timeout must be in (0, 300]")
        self.repository, self.sources, self.timeout = repository, dict(sources), timeout

    async def run(
        self, contract_id: str, call: VerifiedCall, primary: Callable[[], Awaitable[dict[str, Any]]]
    ) -> ContinuityResponse:
        with self.repository() as repository:
            contract = OperationContract.model_validate(
                require(repository.get("continuity_contract", contract_id))
            )
        reasons = []
        if call.authorized is not True:
            reasons.append("authorization_required")
        if not call.actor_tenant or call.actor_tenant != call.resource_tenant:
            reasons.append("tenant_scope_mismatch")
        if call.consumer != contract.consumer:
            reasons.append("consumer_mismatch")
        if reasons:
            raise ContinuityUnavailable(reasons)
        try:
            async with asyncio.timeout(self.timeout):
                data = await primary()
            if (
                not isinstance(data, dict)
                or set(contract.required_fields) - data.keys()
                or not all(evaluate_rules(contract, data).values())
            ):
                raise DependencyUnavailable("Primary response violates the declared field contract")
        except (DependencyUnavailable, TimeoutError):
            with self.repository() as repository:
                record_health(repository, contract_id, healthy=False)
            # No retry: a write may have committed before the dependency failed.
            return await self._fallback(contract_id, contract, call)
        with self.repository() as repository:
            self._verify_contract(repository, contract_id, contract)
            record_health(repository, contract_id, healthy=True)
        return ContinuityResponse(dict(data), "primary")

    @staticmethod
    def _verify_contract(repository, contract_id: str, contract: OperationContract) -> None:
        current = repository.get("continuity_contract", contract_id)
        if current is None or OperationContract.model_validate(current) != contract:
            raise ContinuityUnavailable(["operation_contract_changed"])

    async def _fallback(
        self, contract_id: str, contract: OperationContract, call: VerifiedCall
    ) -> ContinuityResponse:
        if contract.effect != "read" or not contract.allow_cached:
            raise ContinuityUnavailable(["cached_response_not_permitted"])
        try:
            with self.repository() as repository:
                self._verify_contract(repository, contract_id, contract)
                profile = resolve_profile(repository, contract_id)
        except ApplicationError:
            raise ContinuityUnavailable(["no_active_continuity_profile"]) from None
        loader = self.sources.get(profile["profile"]["source"])
        if loader is None:
            raise ContinuityUnavailable(["source_unavailable"])
        try:
            async with asyncio.timeout(self.timeout):
                snapshot = await loader(contract_id, call)
        except (DependencyUnavailable, TimeoutError):
            raise ContinuityUnavailable(["source_unavailable"]) from None
        if snapshot is None:
            raise ContinuityUnavailable(["snapshot_missing"])
        if snapshot.generated_at.utcoffset() is None:
            raise ContinuityUnavailable(["snapshot_clock_invalid"])
        data = dict(snapshot.data)
        try:
            with self.repository() as repository:
                self._verify_contract(repository, contract_id, contract)
                current = resolve_profile(repository, contract_id)
                if (
                    current["id"] != profile["id"]
                    or current["expires_at"] != profile["expires_at"]
                    or activation_digest(current) != activation_digest(profile)
                ):
                    raise ContinuityUnavailable(["continuity_profile_changed"])
                age = (now() - snapshot.generated_at).total_seconds()
                if age < 0 or age > 31536000:
                    raise ContinuityUnavailable(["snapshot_clock_invalid"])
                observed = SnapshotEvidence(
                    available=True,
                    age_seconds=age,
                    fields=[key for key in contract.required_fields if key in data],
                    authorized=call.authorized,
                    same_tenant=call.actor_tenant
                    == call.resource_tenant
                    == snapshot.resource_tenant,
                    consumer_matches=call.consumer == contract.consumer == snapshot.consumer,
                    rule_results=evaluate_rules(contract, data),
                )
                reasons = violations(contract, observed)
                if reasons:
                    raise ContinuityUnavailable(reasons)
                repository.audit(
                    "continuity.cache_served",
                    {"contract_id": contract_id, "profile_id": current["id"], "age_seconds": age},
                )
        except ApplicationError:
            raise ContinuityUnavailable(["no_active_continuity_profile"]) from None
        return ContinuityResponse(data, "cache", current["id"], age)

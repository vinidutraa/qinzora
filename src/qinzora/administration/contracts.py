"""Model proposals and integrator-owned execution grants are separate contracts."""

from functools import reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import Field, create_model

from ..models import Model, Policy


class ManagedRoute(Model):
    service: str = Field(min_length=1, max_length=80)
    route: str = Field(min_length=1, max_length=200, pattern=r"^(\*|/[^?#]*)$")


class StagePolicy(Model):
    action: Literal["stage_policy"]
    policy: Policy


class EnforcePolicy(Model):
    action: Literal["enforce_policy"]
    policy: Policy


class RevokePolicy(Model):
    action: Literal["revoke_policy"]
    policy_id: str = Field(min_length=1, max_length=100)


class ActivateContinuity(Model):
    action: Literal["activate_continuity"]
    profile_id: str = Field(min_length=1, max_length=100)


class RevokeContinuity(Model):
    action: Literal["revoke_continuity"]
    profile_id: str = Field(min_length=1, max_length=100)


Operation = Annotated[
    StagePolicy | EnforcePolicy | RevokePolicy | ActivateContinuity | RevokeContinuity,
    Field(discriminator="action"),
]


class PlanProposal(Model):
    rationale: str = Field(min_length=1, max_length=2000)
    operations: list[Operation] = Field(max_length=5)


class Authority(Model):
    """Trusted application configuration. Never populated from model output."""

    routes: list[ManagedRoute] = Field(min_length=1, max_length=100)
    objective: str = Field(
        default="Maintain tenant isolation and request limits within the managed scopes.",
        min_length=1,
        max_length=1000,
    )
    allow_stage: bool = True
    allow_enforce: bool = False
    revocable_policy_ids: list[str] = Field(default_factory=list, max_length=100)
    maximum_ttl_seconds: int = Field(default=300, ge=1, le=86400)
    minimum_rate_limit: int = Field(default=10, ge=1, le=100000)
    maximum_window_seconds: int = Field(default=60, ge=1, le=3600)
    minimum_legitimate_samples: int = Field(default=1, ge=1, le=100000)
    minimum_abusive_affected: int = Field(default=1, ge=1, le=100000)
    maximum_unknown_affected: int = Field(default=0, ge=0, le=100000)
    maximum_false_positive_rate: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    plan_ttl_seconds: int = Field(default=300, ge=1, le=900)
    continuity_profile_ids: list[str] = Field(default_factory=list, max_length=10)
    maximum_continuity_evidence_age_seconds: int = Field(default=900, ge=1, le=86400)

    def permits(self, policy: Policy) -> bool:
        return self.permits_scope(policy.service, policy.route)

    def permits_scope(self, service: str, route: str) -> bool:
        return any(
            scope.service == service and scope.route in ("*", route) for scope in self.routes
        )


def granted_proposal_type(authority: Authority) -> type[PlanProposal]:
    """Expose only granted operation types in the model's structured schema."""
    operations = []
    if authority.allow_stage:
        operations.append(StagePolicy)
    if authority.allow_enforce:
        policy_type = create_model(
            "GrantedEnforcementPolicy",
            __base__=Policy,
            kind=(Literal["rate_limit", "tenant_isolation"], ...),
            ttl_seconds=(
                int,
                Field(
                    default=min(900, authority.maximum_ttl_seconds),
                    ge=1,
                    le=authority.maximum_ttl_seconds,
                ),
            ),
            threshold=(
                int,
                Field(
                    default=max(20, authority.minimum_rate_limit),
                    ge=authority.minimum_rate_limit,
                    le=100000,
                ),
            ),
            window_seconds=(
                int,
                Field(
                    default=min(60, authority.maximum_window_seconds),
                    ge=1,
                    le=authority.maximum_window_seconds,
                ),
            ),
        )
        operations.append(
            create_model("GrantedEnforcePolicy", __base__=EnforcePolicy, policy=(policy_type, ...))
        )
    if authority.revocable_policy_ids:
        operations.append(RevokePolicy)
    if authority.continuity_profile_ids:
        identifier_type = Literal[tuple(authority.continuity_profile_ids)]
        for action in (ActivateContinuity, RevokeContinuity):
            operations.append(
                create_model(
                    "Granted" + action.__name__, __base__=action, profile_id=(identifier_type, ...)
                )
            )
    if not operations:
        operation_type = Operation
    else:
        operation_type = reduce(or_, operations)
    return create_model(
        "GrantedPlanProposal",
        __base__=PlanProposal,
        operations=(list[operation_type], Field(max_length=5 if operations else 0)),
    )

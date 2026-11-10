"""Application declarations and metadata-only rehearsal inputs."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..models import Model


class ValueRule(Model):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    field: str = Field(min_length=1, max_length=100)
    expected: str | int | bool

    @field_validator("expected")
    @classmethod
    def bounded_string(cls, value):
        if isinstance(value, str) and len(value) > 100:
            raise ValueError("Expected string is too long")
        return value


class OperationContract(Model):
    service: str = Field(min_length=1, max_length=80)
    route: str = Field(min_length=1, max_length=200, pattern=r"^/[^?#]*$")
    consumer: str = Field(min_length=1, max_length=80)
    effect: Literal["read", "write"]
    allow_cached: bool = False
    maximum_age_seconds: int = Field(default=0, ge=0, le=86400)
    required_fields: list[str] = Field(default_factory=list, max_length=50)
    value_rules: list[ValueRule] = Field(default_factory=list, max_length=20)

    @field_validator("required_fields")
    @classmethod
    def valid_fields(cls, value: list[str]) -> list[str]:
        if any(not key.strip() or len(key) > 100 for key in value):
            raise ValueError("Fields must be nonempty names of at most 100 characters")
        if len(value) != len(set(value)):
            raise ValueError("Duplicate required field")
        return sorted(value)

    @model_validator(mode="after")
    def writes_cannot_use_cached_results(self):
        if self.effect == "write" and self.allow_cached:
            raise ValueError("Cached responses cannot authorize or execute writes")
        if len({rule.name for rule in self.value_rules}) != len(self.value_rules):
            raise ValueError("Value rule names must be unique")
        return self


class FallbackProfile(Model):
    name: str = Field(min_length=1, max_length=100)
    service: str = Field(min_length=1, max_length=80)
    route: str = Field(min_length=1, max_length=200, pattern=r"^/[^?#]*$")
    source: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    contract_ids: list[str] = Field(min_length=1, max_length=50)
    ttl_seconds: int = Field(default=60, ge=1, le=86400)

    @field_validator("contract_ids")
    @classmethod
    def unique_contracts(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 100 for item in value) or len(set(value)) != len(value):
            raise ValueError("Contract identifiers must be nonempty and unique")
        return sorted(value)


class SnapshotEvidence(Model):
    available: bool
    age_seconds: float = Field(default=0, ge=0, le=31536000, allow_inf_nan=False)
    fields: list[str] = Field(default_factory=list, max_length=100)
    authorized: bool = False
    same_tenant: bool = False
    consumer_matches: bool = False
    rule_results: dict[str, bool] = Field(default_factory=dict, max_length=20)


class Scenario(Model):
    name: str = Field(min_length=1, max_length=100)
    contract_id: str = Field(min_length=1, max_length=100)
    observed: SnapshotEvidence
    expected: Literal["permit", "deny"]


class Rehearsal(Model):
    scenarios: list[Scenario] = Field(min_length=1, max_length=500)
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Rehearsal capture requires a timezone")
        return value

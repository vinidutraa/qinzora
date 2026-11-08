from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Event(Model):
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=100)
    service: str = Field(min_length=1, max_length=80)
    route: str = Field(min_length=1, max_length=200, pattern=r"^/[^?#]*$")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
    subject: str = Field(min_length=1, max_length=100)
    actor_tenant: str | None = Field(default=None, min_length=1, max_length=80)
    resource_tenant: str | None = Field(default=None, min_length=1, max_length=80)
    status_code: int = Field(default=200, ge=100, le=599)
    latency_ms: float = Field(default=0, ge=0, le=3600000, allow_inf_nan=False)
    expected: Literal["legitimate", "abusive", "unknown"] = "unknown"


class Policy(Model):
    name: str = Field(min_length=1, max_length=100)
    service: str = Field(min_length=1, max_length=80)
    route: str = Field(default="*", min_length=1, max_length=200)
    kind: Literal["rate_limit", "tenant_isolation", "error_burst", "latency"]
    threshold: int = Field(default=20, ge=1, le=100000)
    window_seconds: int = Field(default=60, ge=1, le=3600)
    ttl_seconds: int = Field(default=900, ge=1, le=86400)

    @model_validator(mode="after")
    def valid_route(self):
        if self.route != "*" and (
            not self.route.startswith("/") or "?" in self.route or "#" in self.route
        ):
            raise ValueError("route must be '*' or a path template without query strings")
        return self


class TenantCreate(Model):
    name: str = Field(min_length=1, max_length=100)
    event_limit: int = Field(default=100000, ge=1, le=10000000)


class TenantUpdate(Model):
    enabled: bool


class Activation(Model):
    simulation_id: str
    acknowledge_impact: bool = False


class RouteContract(Model):
    method: str
    path: str = Field(pattern=r"^/")
    authenticated: bool
    tenant_isolation: bool

    @field_validator("method")
    @classmethod
    def uppercase(cls, value):
        return value.upper()


class RegressionRequest(Model):
    baseline: list[RouteContract] = Field(max_length=10000)
    current: list[RouteContract] = Field(max_length=10000)

"""Trusted local operator configuration for a single administration cycle."""

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..models import Model
from ..providers import HTTPStructuredModel
from ..repository import account_transaction
from ..store import Store
from .contracts import Authority
from .controller import Administrator
from .monitor import Monitor


class ManagementConfig(Model):
    database: str = Field(min_length=1)
    account_id: str = Field(min_length=1, max_length=100)
    provider: Literal["ollama", "chat_completions"]
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    authority: Authority


@asynccontextmanager
async def configured_administrator(
    config: ManagementConfig, *, require_credentials: bool = True, timeout: float = 60
) -> AsyncIterator[Administrator]:
    """Local operator access to a database; not an unauthenticated HTTP endpoint."""
    key = os.environ.get(config.api_key_env) if config.api_key_env else None
    if config.api_key_env and not key and require_credentials:
        raise ValueError("Configured model credential environment variable is missing")
    store = Store(config.database)
    # Avoid silently provisioning a new database/account on a configuration typo.
    if not Path(config.database).is_file():
        raise ValueError("Configured Qinzora database does not exist")
    store.initialize()
    async with HTTPStructuredModel(
        config.provider, config.base_url, config.model, api_key=key, timeout=timeout
    ) as model:
        yield Administrator(
            partial(account_transaction, store, config.account_id), model, config.authority
        )


async def run_cycle(
    config: ManagementConfig, *, execute: bool = False, plan_id: str | None = None
) -> dict:
    if plan_id and not execute:
        raise ValueError("Executing an existing plan requires execute=True")
    async with configured_administrator(config, require_credentials=not plan_id) as administrator:
        if plan_id:
            plan = administrator.execute(plan_id)
        else:
            plan = await administrator.propose()
        if execute and not plan_id:
            plan = administrator.execute(plan["id"])
        # The local model context contains configuration; output only the reviewable plan/result.
        return {
            key: value for key, value in plan.items() if key not in ("context", "authority_digest")
        }


async def watch_service(
    config: ManagementConfig,
    stop: asyncio.Event,
    *,
    execute: bool = False,
    interval: float = 30,
    model_timeout: float = 60,
    on_result: Callable[[dict], None] | None = None,
) -> None:
    async with configured_administrator(config, timeout=model_timeout) as administrator:
        monitor = Monitor(
            administrator, config.account_id, execute=execute, model_timeout=model_timeout
        )
        await monitor.watch(stop, interval=interval, on_result=on_result)

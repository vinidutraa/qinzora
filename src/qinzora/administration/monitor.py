"""Durable polling with one expiring owner per account and change-driven inference."""

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from ..errors import ApplicationError
from ..models import now
from ..providers import ModelUnavailable
from .context import capture_context, continuity_revision, fingerprint
from .controller import Administrator


def observation_revision(context: dict) -> str:
    data = {
        key: value for key, value in context.items() if key not in ("created_at", "limitations")
    }
    stamp = datetime.fromisoformat(context["created_at"])
    data["effective_active"] = [
        item["id"]
        for item in context["policies"]
        if item["state"] == "active" and datetime.fromisoformat(item["expires_at"]) > stamp
    ]
    return fingerprint(data)


class Monitor:
    """The host supplies a globally unique account slot, never model-generated.

    A lease protects this monitor slot across processes. It does not elect a
    cluster-wide leader for other slots or for manual/operator transactions.
    """

    def __init__(
        self,
        administrator: Administrator,
        slot: str,
        *,
        execute: bool = False,
        model_timeout: float = 60,
    ):
        if not slot or not 0 < model_timeout <= 300:
            raise ValueError("Invalid monitor slot or model timeout")
        self.administrator = administrator
        self.checkpoint_id = str(uuid5(NAMESPACE_URL, "qinzora:monitor:" + slot))
        self.execute, self.model_timeout = execute, model_timeout
        self.owner = str(uuid4())
        self.lease_seconds = model_timeout + 120

    @contextmanager
    def _owned_repository(self):
        with self.administrator.repository() as repository:
            checkpoint = repository.get("administration_monitor", self.checkpoint_id)
            if (
                not checkpoint
                or checkpoint.get("owner") != self.owner
                or datetime.fromisoformat(checkpoint["lease_until"]) <= now()
            ):
                raise ApplicationError("conflict", "Monitor lease was lost or expired")
            yield repository

    def _claim(self) -> tuple[dict | None, str]:
        with self.administrator.repository() as repository:
            checkpoint = repository.get("administration_monitor", self.checkpoint_id) or {}
            stamp = now()
            if (
                checkpoint.get("owner")
                and datetime.fromisoformat(checkpoint["lease_until"]) > stamp
            ):
                return None, "busy"
            if (
                checkpoint.get("retry_after")
                and datetime.fromisoformat(checkpoint["retry_after"]) > stamp
            ):
                return None, "backoff"
            context = capture_context(repository, self.administrator.authority)
            if (
                checkpoint.get("observed_revision") == observation_revision(context)
                and checkpoint.get("execute") == self.execute
                and not checkpoint.get("retry_after")
            ):
                return None, "unchanged"
            checkpoint.update(
                owner=self.owner,
                lease_until=(stamp + timedelta(seconds=self.lease_seconds)).isoformat(),
            )
            repository.put("administration_monitor", checkpoint, self.checkpoint_id)
            return context, "claimed"

    def _finish(
        self, context: dict | None, plan: dict | None, status: str, retry: bool = False
    ) -> bool:
        with self.administrator.repository() as repository:
            checkpoint = repository.get("administration_monitor", self.checkpoint_id)
            if not checkpoint or checkpoint.get("owner") != self.owner:
                return False
            if context is not None:
                observed = deepcopy(context)
                if plan and plan["state"] == "executed":
                    inventory = {item["id"]: item for item in observed["policies"]}
                    continuity = {item["id"]: item for item in observed["continuity_profiles"]}
                    for result in plan["results"]:
                        if "policy_state" in result:
                            item = result["policy_state"]
                            inventory[item["id"]] = item
                        if "continuity_state" in result:
                            item = deepcopy(result["continuity_state"])
                            item["dependency_health"] = continuity[item["id"]]["dependency_health"]
                            continuity[item["id"]] = item
                    observed["policies"] = sorted(inventory.values(), key=lambda item: item["id"])
                    observed["policy_revision"] = fingerprint(observed["policies"])
                    observed["continuity_profiles"] = sorted(
                        continuity.values(), key=lambda item: item["id"]
                    )
                    observed["continuity_revision"] = continuity_revision(
                        observed["continuity_profiles"]
                    )
                checkpoint["observed_revision"] = observation_revision(observed)
            failures = checkpoint.get("failures", 0) + 1 if retry else 0
            checkpoint.update(
                owner=None,
                execute=self.execute,
                lease_until=None,
                status=status,
                failures=failures,
                retry_after=(
                    now() + timedelta(seconds=min(300, 5 * 2 ** min(failures, 6)))
                ).isoformat()
                if retry
                else None,
            )
            repository.put("administration_monitor", checkpoint, self.checkpoint_id)
            repository.audit(
                "administration.monitor_cycle",
                {"status": status, "plan_id": plan["id"] if plan else None},
            )
            return True

    async def tick(self) -> dict:
        context, status = self._claim()
        if context is None:
            return {"status": status}
        administrator = Administrator(
            self._owned_repository, self.administrator.model, self.administrator.authority
        )
        plan, retry = None, False
        try:
            async with asyncio.timeout(self.model_timeout):
                plan = await administrator.propose()
            # Use the observation actually sent to the model, not an earlier polling snapshot.
            context = plan["context"]
            if self.execute:
                plan = administrator.execute(plan["id"])
            status = plan["state"]
        except (ModelUnavailable, TimeoutError):
            status, retry = "model_unavailable", True
        except ApplicationError:
            status = "rejected"
        except BaseException as failure:
            try:
                self._finish(None, None, "interrupted")
            except Exception:
                failure.add_note("Monitor lease cleanup failed; the lease expires automatically")
            raise
        if not self._finish(context, plan, status, retry):
            return {"status": "lease_lost"}
        return {"status": status, "plan_id": plan["id"] if plan else None}

    async def watch(
        self,
        stop: asyncio.Event,
        *,
        interval: float = 30,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        if not 0 < interval <= 3600:
            raise ValueError("Monitor interval must be in (0, 3600]")
        while not stop.is_set():
            work, stopped = asyncio.create_task(self.tick()), asyncio.create_task(stop.wait())
            try:
                done, _ = await asyncio.wait((work, stopped), return_when=asyncio.FIRST_COMPLETED)
                if work in done:
                    result = work.result()
                    if on_result:
                        on_result(result)
            finally:
                for task in (work, stopped):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(work, stopped, return_exceptions=True)
            if not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), interval)
                except TimeoutError:
                    pass

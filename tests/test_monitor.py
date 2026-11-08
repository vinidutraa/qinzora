import asyncio
from datetime import timedelta

from test_administration import Model, operation
from test_administration import setup as setup
from test_api import post_event

from qinzora.administration.controller import Administrator
from qinzora.administration.monitor import Monitor
from qinzora.models import now
from qinzora.providers import ModelUnavailable


class CountingModel(Model):
    def __init__(self, operations=()):
        super().__init__(list(operations))
        self.calls = 0

    async def generate(self, *args):
        self.calls += 1
        return await super().generate(*args)


def test_new_input_triggers_inference_but_unchanged_input_and_restart_do_not(
    api, tenant, event, setup
):
    repository, authority = setup
    model = CountingModel([operation()])
    administrator = Administrator(repository, model, authority)

    async def run():
        monitor = Monitor(administrator, tenant["id"], execute=True)
        assert (await monitor.tick())["status"] == "executed"
        assert (await monitor.tick())["status"] == "unchanged"
        restarted = Monitor(administrator, tenant["id"], execute=True)
        assert (await restarted.tick())["status"] == "unchanged"
        post_event(api[0], tenant, {**event, "event_id": "new-input"})
        # A model that proposes the same active protection cannot create duplicates.
        assert (await restarted.tick())["status"] == "rejected"
        assert (await restarted.tick())["status"] == "unchanged"

    asyncio.run(run())
    assert model.calls == 2
    with repository() as repo:
        assert len(repo.policies()) == 1


def test_two_monitor_instances_cannot_call_the_model_at_the_same_time(tenant, setup):
    repository, authority = setup

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class BlockingModel(CountingModel):
            async def generate(self, *args):
                entered.set()
                await release.wait()
                return await super().generate(*args)

        model = BlockingModel()
        administrator = Administrator(repository, model, authority)
        first, second = Monitor(administrator, tenant["id"]), Monitor(administrator, tenant["id"])
        task = asyncio.create_task(first.tick())
        await asyncio.wait_for(entered.wait(), 5)
        assert (await second.tick())["status"] == "busy"
        release.set()
        assert (await task)["status"] == "draft"
        assert model.calls == 1

    asyncio.run(run())


def test_provider_outage_backs_off_then_recovers(tenant, setup, monkeypatch):
    repository, authority = setup

    class FailingModel(CountingModel):
        async def generate(self, *args):
            if not self.calls:
                self.calls += 1
                raise ModelUnavailable("unavailable")
            return await super().generate(*args)

    async def run():
        model = FailingModel()
        monitor = Monitor(Administrator(repository, model, authority), tenant["id"])
        assert (await monitor.tick())["status"] == "model_unavailable"
        assert (await monitor.tick())["status"] == "backoff"
        assert model.calls == 1
        stamp = now() + timedelta(seconds=30)
        monkeypatch.setattr("qinzora.administration.monitor.now", lambda: stamp)
        assert (await monitor.tick())["status"] == "draft"
        assert (await monitor.tick())["status"] == "unchanged"
        assert model.calls == 2

    asyncio.run(run())


def test_stop_cancels_inference_and_releases_the_lease(tenant, setup):
    repository, authority = setup

    async def run():
        entered, cancelled, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class BlockingModel:
            async def generate(self, *args):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        monitor = Monitor(Administrator(repository, BlockingModel(), authority), tenant["id"])
        task = asyncio.create_task(monitor.watch(stop))
        await asyncio.wait_for(entered.wait(), 5)
        stop.set()
        await asyncio.wait_for(task, 5)
        assert cancelled.is_set()
        replacement = Monitor(Administrator(repository, CountingModel(), authority), tenant["id"])
        assert (await replacement.tick())["status"] == "draft"

    asyncio.run(run())


def test_expired_owner_cannot_publish_or_execute_after_another_owner_takes_over(tenant, setup):
    repository, authority = setup

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class SlowModel(CountingModel):
            async def generate(self, *args):
                entered.set()
                await release.wait()
                return await super().generate(*args)

        first = Monitor(
            Administrator(repository, SlowModel([operation()]), authority),
            tenant["id"],
            execute=True,
        )
        task = asyncio.create_task(first.tick())
        await asyncio.wait_for(entered.wait(), 5)
        with repository() as repo:
            checkpoint = repo.get("administration_monitor", first.checkpoint_id)
            checkpoint["lease_until"] = (now() - timedelta(seconds=1)).isoformat()
            repo.put("administration_monitor", checkpoint, first.checkpoint_id)
        second = Monitor(Administrator(repository, CountingModel(), authority), tenant["id"])
        assert (await second.tick())["status"] == "draft"
        release.set()
        assert (await task)["status"] == "lease_lost"
        with repository() as repo:
            assert not repo.policies()

    asyncio.run(run())


def test_events_arriving_during_inference_are_not_marked_as_already_seen(api, tenant, event, setup):
    repository, authority = setup

    class NewEventModel(CountingModel):
        async def generate(self, *args):
            if not self.calls:
                post_event(api[0], tenant, {**event, "event_id": "during-inference"})
            return await super().generate(*args)

    async def run():
        model = NewEventModel()
        monitor = Monitor(Administrator(repository, model, authority), tenant["id"], execute=True)
        assert (await monitor.tick())["status"] == "executed"
        assert (await monitor.tick())["status"] == "executed"
        assert (await monitor.tick())["status"] == "unchanged"
        assert model.calls == 2

    asyncio.run(run())


def test_policy_expiry_triggers_reassessment_without_new_events(tenant, setup, monkeypatch):
    repository, authority = setup
    model = CountingModel([operation()])

    async def run():
        monitor = Monitor(Administrator(repository, model, authority), tenant["id"], execute=True)
        assert (await monitor.tick())["status"] == "executed"
        model.operations = []
        stamp = now() + timedelta(seconds=61)
        for module in ("monitor", "context", "controller"):
            monkeypatch.setattr(f"qinzora.administration.{module}.now", lambda: stamp)
        assert (await monitor.tick())["status"] == "executed"
        assert model.calls == 2

    asyncio.run(run())


def test_model_timeout_cancels_request_and_enters_backoff(tenant, setup):
    repository, authority = setup

    async def run():
        cancelled = asyncio.Event()

        class SlowModel:
            async def generate(self, *args):
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        monitor = Monitor(
            Administrator(repository, SlowModel(), authority), tenant["id"], model_timeout=0.01
        )
        assert (await monitor.tick())["status"] == "model_unavailable"
        assert cancelled.is_set()
        assert (await monitor.tick())["status"] == "backoff"
        with repository() as repo:
            checkpoint = repo.get("administration_monitor", monitor.checkpoint_id)
            assert checkpoint["owner"] is None

    asyncio.run(run())


def test_enabling_execution_is_not_skipped_by_a_preview_checkpoint(tenant, setup):
    repository, authority = setup
    model = CountingModel()
    administrator = Administrator(repository, model, authority)

    async def run():
        preview = Monitor(administrator, tenant["id"])
        assert (await preview.tick())["status"] == "draft"
        active = Monitor(administrator, tenant["id"], execute=True)
        assert (await active.tick())["status"] == "executed"
        assert model.calls == 2

    asyncio.run(run())

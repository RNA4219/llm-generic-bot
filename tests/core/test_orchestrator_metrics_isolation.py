import asyncio

from llm_generic_bot.core.orchestrator import Orchestrator, PermitDecision
from llm_generic_bot.infra import metrics as metrics_module
from llm_generic_bot.infra.metrics import MetricsService


class StubSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []

    async def send(self, text: str, channel: str | None, *, job: str) -> None:
        self.calls.append((text, channel, job))


class StubCooldownGate:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def note_post(self, platform: str, channel: str, job: str) -> None:
        self.calls.append((platform, channel, job))


class StubNearDuplicateFilter:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def permit(self, text: str) -> bool:
        self.requests.append(text)
        return True


def test_weekly_snapshot_is_isolated_between_instances() -> None:
    metrics_module.reset_for_test()

    async def run() -> None:
        sender_a = StubSender()
        cooldown = StubCooldownGate()
        dedupe = StubNearDuplicateFilter()

        def permit(_: str, __: str | None, job: str) -> PermitDecision:
            return PermitDecision.allow(job=job)

        orchestrator_a = Orchestrator(
            sender=sender_a,
            cooldown=cooldown,
            dedupe=dedupe,
            permit=permit,
            metrics=MetricsService(),
            platform="test-platform",
        )
        orchestrator_b: Orchestrator | None = None

        try:
            await orchestrator_a.send("hello", job="job-a")

            orchestrator_b = Orchestrator(
                sender=StubSender(),
                cooldown=cooldown,
                dedupe=dedupe,
                permit=permit,
                metrics=None,
                platform="test-platform",
            )

            await orchestrator_b.send("world", job="job-b")

            snapshot = await orchestrator_a.weekly_snapshot()

            success_counters = snapshot.counters.get("send.success", {})
            assert success_counters, "expected at least one send.success counter"
            recorded_jobs = {
                dict(tags).get("job")
                for tags in success_counters
            }
            assert recorded_jobs == {"job-a"}
        finally:
            await orchestrator_a.close()
            if orchestrator_b is not None:
                await orchestrator_b.close()

    asyncio.run(run())


def test_metrics_module_weekly_snapshot_ignores_disabled_backend() -> None:
    metrics_module.reset_for_test()

    async def run() -> None:
        sender_a = StubSender()
        cooldown = StubCooldownGate()
        dedupe = StubNearDuplicateFilter()

        def permit(_: str, __: str | None, job: str) -> PermitDecision:
            return PermitDecision.allow(job=job)

        orchestrator_a = Orchestrator(
            sender=sender_a,
            cooldown=cooldown,
            dedupe=dedupe,
            permit=permit,
            metrics=MetricsService(),
            platform="test-platform",
        )
        orchestrator_b: Orchestrator | None = None

        try:
            await orchestrator_a.send("hello", job="job-a")

            orchestrator_b = Orchestrator(
                sender=StubSender(),
                cooldown=cooldown,
                dedupe=dedupe,
                permit=permit,
                metrics=None,
                platform="test-platform",
            )

            await orchestrator_b.send("world", job="job-b")

            snapshot = metrics_module.weekly_snapshot()
            success_rate = snapshot.get("success_rate", {})
            assert success_rate, "expected at least one success_rate entry"
            assert set(success_rate) == {"job-a"}
        finally:
            await orchestrator_a.close()
            if orchestrator_b is not None:
                await orchestrator_b.close()

    asyncio.run(run())

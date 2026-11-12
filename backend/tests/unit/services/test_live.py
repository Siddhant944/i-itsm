"""The live-update hub (P4.8): who gets a push, and that a push crosses threads safely."""

import asyncio
import threading

from starlette.websockets import WebSocketDisconnect

from app.api.routers.ws import _close
from app.services.live import MAX_QUEUED, LiveHub


def test_a_push_reaches_the_people_named_and_everyone_who_watches_all() -> None:
    async def scenario() -> list[int]:
        hub = LiveHub()
        reporter = hub.subscribe(1, watches_all=False)
        stranger = hub.subscribe(2, watches_all=False)
        lead = hub.subscribe(3, watches_all=True)
        # Route handlers publish from a worker thread, not the loop.
        sent: list[int] = []
        worker = threading.Thread(
            target=lambda: sent.append(hub.publish({1}, {"type": "incident", "incident_id": "X"}))
        )
        worker.start()
        worker.join()
        await asyncio.sleep(0)  # let the loop run the queued callbacks
        assert reporter.queue.get_nowait() == {"type": "incident", "incident_id": "X"}
        assert lead.queue.get_nowait()["incident_id"] == "X"
        assert stranger.queue.empty()  # BR-01: no push about someone else's incident
        hub.unsubscribe(reporter)
        assert hub.connections == 2
        return sent

    assert asyncio.run(scenario()) == [2]


def test_a_client_that_stops_reading_loses_updates_rather_than_memory() -> None:
    async def scenario() -> int:
        hub = LiveHub()
        slow = hub.subscribe(1, watches_all=False)
        for n in range(MAX_QUEUED + 5):
            hub.publish({1}, {"n": n})
        await asyncio.sleep(0)
        return slow.queue.qsize()

    assert asyncio.run(scenario()) == MAX_QUEUED


def test_a_socket_whose_loop_has_closed_is_forgotten() -> None:
    hub = LiveHub()

    async def open_one() -> None:
        hub.subscribe(1, watches_all=False)

    asyncio.run(open_one())  # the loop closes when this returns
    assert hub.publish({1}, {"type": "incident"}) == 1
    assert hub.connections == 0


def test_closing_a_socket_the_browser_already_left_is_not_an_error() -> None:
    """React mounts effects twice in development, so the first socket often goes at once;
    uvicorn then raises WebSocketDisconnect from close() (seen in the live e2e spec)."""

    class Gone:
        async def close(self, code: int) -> None:
            raise WebSocketDisconnect(1006)

    asyncio.run(_close(Gone()))  # type: ignore[arg-type]


def test_followers_of_a_duplicate_hear_when_the_incident_they_follow_changes() -> None:
    """D-005: the follower's page shows the parent's status; it is refreshed by their own id."""
    from datetime import UTC, datetime

    from app.core.clock import FakeClock
    from app.domain.incident import CancelReason, IncidentFactory
    from app.repositories.memory import InMemoryUnitOfWork
    from app.services.live import LivePublisher

    clock = FakeClock(datetime(2026, 11, 12, 9, 0, tzinfo=UTC))
    uow = InMemoryUnitOfWork()

    def made(sequence: int, reporter: int) -> str:
        incident = IncidentFactory.create(
            sequence=sequence,
            clock=clock,
            reporter_id=reporter,
            title="Fee portal down",
            description="Down",
            service_id=1,
            impact=2,
            urgency=2,
        )
        uow.incidents.add(incident)
        return incident.id

    parent, child = made(1, 1), made(2, 2)
    linked = uow.incidents.get(child)
    linked.cancel(2, clock, CancelReason.DUPLICATE, parent)
    uow.incidents.save(linked)

    async def scenario() -> list[dict[str, str]]:
        hub = LiveHub()
        follower = hub.subscribe(2, watches_all=False)
        LivePublisher(uow, hub).incident_changed(parent)
        await asyncio.sleep(0)
        got = []
        while not follower.queue.empty():
            got.append(follower.queue.get_nowait())
        return got

    assert [m["incident_id"] for m in asyncio.run(scenario())] == [child]

"""Chromium launch cap works across event loops (brand scrapes run on their own loop since 2026-10-30)."""
import asyncio
import threading

from app.services.scraper import _ChromiumSlots


def test_cap_holds_across_loops_and_threads():
    slots = _ChromiumSlots(2)
    active, peak, lock = [0], [0], threading.Lock()

    async def job():
        async with slots:
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            await asyncio.sleep(0.2)
            with lock:
                active[0] -= 1

    async def three():
        await asyncio.gather(job(), job(), job())

    threads = [threading.Thread(target=lambda: asyncio.run(three())) for _ in range(2)]
    for t in threads:
        t.start()
    asyncio.run(three())
    for t in threads:
        t.join()
    assert peak[0] == 2 and active[0] == 0


def test_slot_released_when_body_raises():
    slots = _ChromiumSlots(1)

    async def boom():
        async with slots:
            raise ValueError

    for _ in range(2):
        try:
            asyncio.run(boom())
        except ValueError:
            pass
    asyncio.run(asyncio.wait_for(slots.__aenter__(), 1))   # would time out if a slot leaked

from __future__ import annotations

import asyncio

from arbiter.console.hub import ConsoleHub
from arbiter.console.sources import CallbackSource


async def _noop(data: bytes) -> None:
    pass


async def test_channels_all_and_any():
    hub = ConsoleHub("b")
    for name in ("uart:app", "uart:tfm", "rtt"):
        await hub.attach(CallbackSource(name, _noop))
    hub.feed(b"*** Booting nRF Connect SDK ***\r\n", "uart:app")
    hub.feed(b"[Sec Thread] Secure image initializing!\r\n", "uart:tfm")
    hub.feed(b"<inf> app: hello over rtt\n", "rtt")
    all_text = hub.read(0, 4096, "all")[0].decode()
    assert "[uart:app] *** Booting" in all_text and "[rtt] <inf>" in all_text
    assert "Secure image" not in all_text  # TF-M noise stays out of "all"
    assert b"Secure image" in hub.read(0, 4096, "uart:tfm")[0]
    m = await hub.expect(r"hello over (\w+)", 1, 0, hub.resolve_many("any"))
    assert m["matched"] and m["channel"] == "rtt" and m["groups"] == ["rtt"]
    m = await hub.expect(r"hello over", 0.05, 0, [hub.primary])
    assert not m["matched"]
    assert hub.new_lines({}, exclude={"uart:app"}) == {"uart:tfm": 1, "rtt": 1}


async def test_primary_switch_and_cursors():
    hub = ConsoleHub("b")
    hub.feed(b"uart line\n", "uart:app")
    hub.set_primary("rtt")
    assert hub.resolve("console") == "rtt"
    waiter = asyncio.create_task(hub.expect("ready", 1, hub.ends(), None))
    await asyncio.sleep(0.01)
    hub.feed(b"ready\n", "rtt")
    m = await waiter
    assert m["matched"] and m["channel"] == "rtt" and m["cursor"] == hub.end("rtt") - 1
    hub.annotate("[arbiter] note")
    assert b"[arbiter] note" in hub.read(0, 4096, "rtt")[0]
    assert b"[arbiter] note" not in hub.read(0, 4096, "uart:app")[0]

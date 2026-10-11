from __future__ import annotations

import pytest
from arbiter import scheduler as sch
from arbiter.errors import ArbiterError

from .conftest import FakeClock


def make(clock: FakeClock, boards=("b1",)) -> sch.Scheduler:
    s = sch.Scheduler(sch.Timing(), clock)
    for b in boards:
        s.add_board(b, "nrf9161dk/nrf9161/ns", ["lte"])
    return s


def granted(entry: sch.QueueEntry) -> str:
    assert entry.lease_token, "ticket was not granted"
    return entry.lease_token


def agent(s: sch.Scheduler, name: str, **kw) -> str:
    return s.register_session("claude", name, **kw).id


async def test_grant_then_queue_then_handover(clock):
    s = make(clock)
    a, b = agent(s, "A"), agent(s, "B")
    ea = s.acquire(a, "b1", "flash fw")
    assert s.ticket_status(ea.ticket)["status"] == "granted"
    eb = s.acquire(b, "nrf9161dk", "test")
    st = s.ticket_status(eb.ticket)
    assert st["status"] == "queued" and st["position"] == 1
    assert st["boards"][0]["holder"] == "A"
    token = granted(ea)
    s.release(token)
    assert s.ticket_status(eb.ticket)["status"] == "granted"
    with pytest.raises(ArbiterError) as e:
        s.check(token)
    assert e.value.code == "LEASE_REVOKED"


async def test_acquire_is_idempotent(clock):
    s = make(clock)
    a, b = agent(s, "A"), agent(s, "B")
    s.acquire(a, "b1")
    e1 = s.acquire(b, "b1")
    e2 = s.acquire(b, "b1")
    assert e1.ticket == e2.ticket and len(s.queue) == 1
    assert s.acquire(a, "b1").state == "granted"


async def test_priority_order_and_agent_cap(clock):
    s = make(clock)
    holder, low, agent_hi, human = (
        agent(s, "H"),
        agent(s, "L"),
        agent(s, "X"),
        s.register_session("human", "Fame").id,
    )
    s.acquire(holder, "b1")
    e_low = s.acquire(low, "b1", priority="low")
    e_agent = s.acquire(agent_hi, "b1", priority="urgent")
    assert e_agent.priority == sch.AGENT_MAX_PRIORITY  # agents can't jump the queue
    e_h = s.acquire(human, "b1", priority="urgent", human=True)
    assert [e.ticket for e in s.queue] == [e_h.ticket, e_agent.ticket, e_low.ticket]


async def test_move_pin_and_bump(clock):
    s = make(clock)
    h = agent(s, "H")
    s.acquire(h, "b1")
    ids = [agent(s, n) for n in "ABC"]
    es = [s.acquire(i, "b1") for i in ids]
    s.move(es[2].ticket, 0)
    assert [e.ticket for e in s.queue] == [es[2].ticket, es[0].ticket, es[1].ticket]
    s.move(es[2].ticket, 2)
    assert [e.ticket for e in s.queue] == [es[0].ticket, es[1].ticket, es[2].ticket]
    s.move(es[2].ticket, 1)
    assert [e.ticket for e in s.queue] == [es[0].ticket, es[2].ticket, es[1].ticket]
    s.pin(es[1].ticket)
    assert s.queue[0].ticket == es[1].ticket
    s.bump_session(ids[0], "urgent")
    assert s.queue[0].ticket == es[1].ticket  # pinned still first
    assert s.queue[1].ticket == es[0].ticket


async def test_pause_resume_keeps_lease(clock):
    s = make(clock)
    a = agent(s, "A")
    tok = granted(s.acquire(a, "b1"))
    s.pause("b1", "human:Fame", "scope probing")
    with pytest.raises(ArbiterError) as e:
        s.check(tok)
    assert e.value.code == "LEASE_PAUSED" and e.value.extra["by"] == "human:Fame"
    assert s.boards["b1"].state == sch.PAUSED
    assert any(i["kind"] == "paused" for i in s.pop_inbox(a))
    s.resume("b1")
    assert s.check(tok).state == sch.ACTIVE


async def test_pause_draining_then_finish(clock):
    s = make(clock)
    tok = granted(s.acquire(agent(s, "A"), "b1"))
    s.pause("b1", "human", draining=True)
    assert s.leases[tok].state == sch.PAUSING and s.boards["b1"].state == sch.LEASED
    s.finish_pause(tok)
    assert s.boards["b1"].state == sch.PAUSED


async def test_take_revokes_and_requeues_at_head(clock):
    s = make(clock)
    a, b = agent(s, "A"), agent(s, "B")
    ea = s.acquire(a, "b1")
    tok = granted(ea)
    eb = s.acquire(b, "b1")
    s.take("b1", "human:Fame")
    assert s.boards["b1"].state == sch.HUMAN
    with pytest.raises(ArbiterError) as e:
        s.check(tok)
    assert e.value.code == "LEASE_REVOKED" and e.value.extra["ticket"] == ea.ticket
    assert s.queue[0].ticket == ea.ticket and s.queue[1].ticket == eb.ticket
    s.resume("b1")  # human done
    assert s.ticket_status(ea.ticket)["status"] == "granted"


async def test_heartbeat_loss_grace_and_reclaim(clock):
    s = make(clock)
    a = agent(s, "A", heartbeat=True)
    tok = granted(s.acquire(a, "b1"))
    s.check(tok)
    clock.advance(30)
    s.tick()
    assert s.leases[tok].state == sch.EXPIRING
    s.heartbeat(a)  # shim came back
    assert s.leases[tok].state == sch.ACTIVE
    clock.advance(30)
    s.tick()
    clock.advance(31)
    s.tick()
    assert s.leases[tok].state == sch.REVOKED
    assert s.boards["b1"].state == sch.AVAILABLE


async def test_restarted_agent_gets_its_board_back(clock):
    """The MCP server exits (session ended, lease in grace) and the same agent starts a
    new one: it is the same session again and keeps its lease instead of queueing."""
    s = make(clock)
    a = s.register_session("claude", "A", external_id="ext-A", heartbeat=True).id
    tok = granted(s.acquire(a, "b1"))
    s.end_session(a, release=False)
    assert s.leases[tok].state == sch.EXPIRING
    clock.advance(5)
    again = s.register_session("claude", "A", external_id="ext-A", heartbeat=True)
    assert again.id == a and not again.ended
    assert s.leases[tok].state == sch.ACTIVE and s.boards["b1"].state == sch.LEASED


async def test_ended_session_without_lease_is_not_reused(clock):
    s = make(clock)
    a = s.register_session("claude", "A", external_id="ext-A").id
    s.end_session(a)
    assert s.register_session("claude", "A", external_id="ext-A").id != a


async def test_ttl_expiry_and_extend(clock):
    s = make(clock)
    tok = granted(s.acquire(agent(s, "A"), "b1"))
    s.check(tok)
    clock.advance(14 * 60)
    s.extend(tok, 10)
    clock.advance(10 * 60)
    s.tick()
    assert s.leases[tok].state == sch.ACTIVE
    clock.advance(6 * 60)
    s.tick()
    assert s.leases[tok].state == sch.EXPIRED


async def test_unclaimed_grant_expires(clock):
    s = make(clock)
    a, b = agent(s, "A"), agent(s, "B")
    ea = s.acquire(a, "b1")
    s.check(granted(ea))
    eb = s.acquire(b, "b1")
    s.release(granted(ea))
    clock.advance(121)
    s.tick()
    with pytest.raises(ArbiterError) as e:
        s.ticket_status(eb.ticket)
    assert e.value.code == "TICKET_EXPIRED"
    assert s.boards["b1"].state == sch.AVAILABLE


async def test_ticket_expires_without_polls(clock):
    s = make(clock)
    s.acquire(agent(s, "A"), "b1")
    e = s.acquire(agent(s, "B"), "b1")
    clock.advance(91)
    s.tick()
    with pytest.raises(ArbiterError) as err:
        s.ticket_status(e.ticket)
    assert err.value.code == "TICKET_EXPIRED"


async def test_wait_returns_on_grant(clock):
    import asyncio

    s = make(clock)
    tok = granted(s.acquire(agent(s, "A"), "b1"))
    e = s.acquire(agent(s, "B"), "b1")
    waiter = asyncio.create_task(s.wait(e.ticket, 5))
    await asyncio.sleep(0.01)
    s.release(tok)
    st = await asyncio.wait_for(waiter, 1)
    assert st["status"] == "granted"


async def test_selector_by_tags_and_unknown(clock):
    s = make(clock, boards=("b1", "b2"))
    s.boards["b2"].tags = ["ppk2"]
    e = s.acquire(agent(s, "A"), {"platform": "nrf9161dk", "tags": ["ppk2"]})
    assert s.leases[granted(e)].board_id == "b2"
    with pytest.raises(ArbiterError):
        s.acquire(agent(s, "B"), "stm32")


async def test_maintenance_and_offline_block_dispatch(clock):
    s = make(clock)
    s.set_maintenance("b1", True)
    e = s.acquire(agent(s, "A"), "b1")
    assert e.state == "queued"
    s.set_maintenance("b1", False)
    assert e.state == "granted"
    s.release(granted(e))
    s.set_present("b1", False)
    e2 = s.acquire(agent(s, "B"), "b1")
    assert e2.state == "queued"
    s.set_present("b1", True)
    assert e2.state == "granted"


async def test_dump_restore_makes_leases_reclaimable(clock):
    s = make(clock)
    a = agent(s, "A")
    tok = granted(s.acquire(a, "b1"))
    q = s.acquire(agent(s, "B"), "b1")
    data = s.dump()
    s2 = make(clock)
    s2.restore(data)
    assert s2.leases[tok].state == sch.EXPIRING
    assert [e.ticket for e in s2.queue] == [q.ticket]
    s2.reclaim(tok, a)
    assert s2.check(tok).state == sch.ACTIVE

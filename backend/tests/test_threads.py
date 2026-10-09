from __future__ import annotations

from arbiter.drivers.sim import SIM_THREADS
from arbiter.threads import assess, parse_analyzer, parse_thread_list

from .test_service import done, lease_for

ANALYZER = """\
[00:00:10.000,000] <inf> thread_analyzer:  Thread analyze:
[00:00:10.000,000] <inf> thread_analyzer:   BT RX               : STACK: unused 64 usage 1984 / 2048 (96 %); CPU: 1 %
[00:00:10.000,000] <inf> thread_analyzer:       : Total CPU cycles used: 1234
[00:00:10.000,000] <inf> thread_analyzer:   main                : STACK: unused 400 usage 624 / 1024 (60 %); CPU: 0 %
[00:00:10.000,000] <inf> thread_analyzer:   ISR0                : STACK: unused 1808 usage 240 / 2048 (11 %)
[00:00:10.100,000] <inf> app: done
"""


def test_parse_kernel_thread_list():
    threads, unknown = parse_thread_list(SIM_THREADS.replace("\r", ""))
    assert not unknown
    assert [t["name"] for t in threads] == ["shell_uart", "sysworkq", "idle"]
    assert threads[0]["current"] is True
    work = threads[1]
    assert work["priority"] == -1 and work["state"] == "pending"
    assert (work["stack_size"], work["stack_used"], work["stack_pct"]) == (1024, 928, 91)
    assert threads[2]["state"] == "ready"


def test_unknown_stack_use_is_reported():
    text = " 0x2000 main\n\toptions: 0x0, priority: 0 timeout: 0\n\tUnable to determine unused stack size (-88)\n"
    threads, unknown = parse_thread_list(text)
    assert unknown and threads[0]["name"] == "main" and "stack_pct" not in threads[0]


def test_parse_thread_analyzer_report():
    threads = parse_analyzer(ANALYZER)
    assert [t["name"] for t in threads] == ["BT RX", "main", "ISR0"]
    assert threads[0]["cpu_pct"] == 1 and threads[0]["stack_pct"] == 97
    warnings = assess(threads)
    assert len(warnings) == 1 and "CONFIG_BT_RX_STACK_SIZE" in warnings[0]


async def test_thread_health_uses_the_kernel_shell(arb, build_dir):
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.expect(s, tok, r"uart:~\$ ", 5)
    res = await arb.thread_health(s, tok)
    assert res["source"] == "shell: kernel thread list"
    assert len(res["threads"]) == 3
    assert res["ok"] is False
    assert res["warnings"] == [
        "sysworkq has used 91 % of its 1024 B stack (peak so far): raise "
        "CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE."
    ]
    assert (await arb.thread_health(s, tok, warn_pct=95))["ok"] is True

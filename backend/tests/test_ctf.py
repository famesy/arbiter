from __future__ import annotations

from pathlib import Path

from arbiter import ctf

from .test_service import done, lease_for

TEXT = """\
[00:00:01.000000000] (+?.?????????) thread_switched_in: { thread_id = 536871944, name = "main" }
[00:00:01.000100000] (+0.000100000) isr_enter: { }
[00:00:01.000200000] (+0.000100000) isr_exit: { }
[00:00:01.500000000] (+0.499800000) thread_switched_in: { thread_id = 536871000, name = "idle" }
[00:00:02.000000000] (+0.500000000) thread_switched_in: { thread_id = 536871944, name = "main" }
not an event line
"""


def test_summarize_counts_events_and_switches():
    s = ctf.summarize(TEXT)
    assert s["events"] == 5 and s["span_s"] == 1.0
    assert s["by_event"]["thread_switched_in"] == 3
    assert s["thread_switches"] == {"main": 2, "idle": 1}
    assert s["isr_per_s"] == 1.0


def fake_zephyr(build: Path) -> None:
    zephyr = build.parent / "zephyr-base"
    meta = zephyr / "subsys" / "tracing" / "ctf" / "tsdl" / "metadata"
    meta.parent.mkdir(parents=True)
    meta.write_text("/* CTF 1.8 */")
    (build / "CMakeCache.txt").write_text(f"ZEPHYR_BASE:PATH={zephyr}\n")


async def test_tracing_captures_and_decodes(arb, build_dir, monkeypatch):
    fake_zephyr(build_dir)
    seen: list[Path] = []

    def fake_babeltrace(directory: Path, timeout_s: float = 120) -> tuple[str, None]:
        seen.append(directory)
        return TEXT, None

    monkeypatch.setattr(ctf, "babeltrace", fake_babeltrace)
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    res = await arb.tracing(s, tok, "start")
    assert res["status"] == "capturing" and res["channel"] == "uart:app"
    arb.boards["sim-1"].hub.feed(b"\xc1\x1f\xfc\xc1\x00\x01", "uart:app")
    res = await arb.tracing(s, tok, "stop")
    assert res["bytes"] == 6
    d = seen[0]
    assert (d / "metadata").read_text() == "/* CTF 1.8 */"
    assert (d / "channel0_0").read_bytes() == b"\xc1\x1f\xfc\xc1\x00\x01"
    assert res["summary"]["thread_switches"]["main"] == 2
    assert (await arb.tracing(s, tok, "status"))["status"] == "not_running"


async def test_tracing_without_babeltrace_points_to_trace_compass(arb, build_dir, monkeypatch):
    fake_zephyr(build_dir)
    monkeypatch.setattr("arbiter.ctf.shutil.which", lambda _name: None)
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.tracing(s, tok, "start")
    arb.boards["sim-1"].hub.feed(b"\x00\x01", "uart:app")
    res = await arb.tracing(s, tok, "stop")
    assert "Trace Compass" in res["hint"] and res["trace_dir"]

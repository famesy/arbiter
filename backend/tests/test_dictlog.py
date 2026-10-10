from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from arbiter.dictlog import decode, find_tools, prepare

from .test_service import done, lease_for

# Stands in for Zephyr's log_parser.py: prints its flags, then the log file's lines.
PARSER = """
import sys
args = sys.argv[1:]
flags = [a for a in args if a.startswith("--")]
db, log = [a for a in args if not a.startswith("--")]
print("flags:", " ".join(flags) or "-")
print("db:", db.endswith("log_dictionary.json"))
for line in open(log, "rb").read().splitlines():
    print("decoded", line.decode())
"""


def fake_zephyr(build: Path) -> None:
    zephyr = build.parent / "zephyr-base"
    parser = zephyr / "scripts" / "logging" / "dictionary" / "log_parser.py"
    parser.parent.mkdir(parents=True)
    parser.write_text(textwrap.dedent(PARSER))
    (build / "CMakeCache.txt").write_text(
        f"ZEPHYR_BASE:PATH={zephyr}\nPython3_EXECUTABLE:FILEPATH={sys.executable}\n"
    )
    (build / "zephyr" / "log_dictionary.json").write_text("{}")


def test_prepare_spots_hex_output():
    assert prepare(b"##ZLOGV1##0102##ZLOGV1##")[1] == ["--hex"]
    data, flags = prepare(b"*** Booting ***\r\n0a0b0c0d0e0f10111213\r\n1415161718191a1b\r\n")
    assert flags == ["--hex", "--rawhex"]
    assert data == b"0a0b0c0d0e0f10111213\n1415161718191a1b\n"
    assert prepare(b"\x01\x02\xff\x00binary")[1] == []


def test_find_tools_says_what_is_missing(build_dir):
    assert "CONFIG_LOG_DICTIONARY_SUPPORT" in str(find_tools(build_dir, build_dir))
    (build_dir / "zephyr" / "log_dictionary.json").write_text("{}")
    assert "ZEPHYR_BASE" in str(find_tools(build_dir, build_dir))


def test_decode_runs_the_parser(build_dir, tmp_path):
    fake_zephyr(build_dir)
    tools = find_tools(build_dir, build_dir)
    assert not isinstance(tools, str)
    res = decode(b"0a0b0c0d\n0e0f1011\n", tools, tmp_path / "work")
    assert res["ok"] and res["format"] == "hex", res
    assert res["untrusted_device_output"].splitlines() == [
        "flags: --hex --rawhex",
        "db: True",
        "decoded 0a0b0c0d",
        "decoded 0e0f1011",
    ]
    assert decode(b"", tools, tmp_path)["ok"] is False


async def test_decode_log_reads_since_the_flash(arb, build_dir):
    fake_zephyr(build_dir)
    s, tok = await lease_for(arb)
    await done(arb, await arb.flash(s, tok, str(build_dir)))
    await arb.expect(s, tok, r"uart:~\$ ", 5)
    res = await arb.decode_log(s, tok)
    assert res["ok"] and res["format"] == "binary", res
    assert "decoded *** Booting" in res["untrusted_device_output"]

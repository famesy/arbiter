from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from arbiter.history import named_tests
from arbiter.imageinfo import describe_build, parse_dts_partitions, parse_partitions

from .test_service import done, lease_for

DATA = Path(__file__).parent / "data" / "zephyr_shell"
PARTITIONS = """\
app:
  address: 0x8000
  end_address: 0x80000
  region: flash_primary
  size: 0x78000
mcuboot:
  address: 0x0
  end_address: 0x8000
  placement:
    before:
    - mcuboot_primary
  region: flash_primary
  size: 0x8000
"""

# Trimmed from an NCS v3.4.1 nrf9161dk/nrf9161/ns build (no Partition Manager).
DTS = """/ {
	chosen {
		zephyr,code-partition = &slot0_ns_partition; /* in nrf9161dk_nrf9161_ns.dts:15 */
	};
	soc {
		flash-controller@40039000 {
			flash0: flash@0 {
				reg = < 0x0 0x100000 >;
				partitions {
					ranges;
					boot_partition: partition@0 {
						label = "mcuboot";
						reg = < 0x0 0x10000 >; /* in nrf91xx_partition.dtsi:35 */
					};

					/* node '/soc/flash-controller@40039000/flash@0/partitions/partition@10000' */
					slot0_partition: partition@10000 {
						label = "image-0";
						reg = < 0x10000 0x70000 >;
						ranges = < 0x0 0x10000 0x70000 >;
						slot0_s_partition: partition@0 {
							label = "image-0-secure";
							reg = < 0x0 0x40000 >;
						};
						slot0_ns_partition: partition@40000 {
							label = "image-0-nonsecure";
							reg = < 0x40000 0x30000 >;
						};
					};
					storage_partition: partition@f8000 {
						label = "storage";
						reg = < 0xf8000 0x8000 >;
					};
				};
			};
		};
	};
};
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def app(tmp_path: Path) -> tuple[Path, Path]:
    """An app repo with one commit, and a build of it."""
    src = tmp_path / "fw"
    src.mkdir()
    (src / "main.c").write_text("int main(void) { return 0; }\n")
    git(src, "init", "-q")
    git(src, "add", ".")
    git(src, "commit", "-qm", "first")
    build = src / "build"
    (build / "zephyr").mkdir(parents=True)
    (build / "zephyr" / ".config").write_text(
        'CONFIG_BOARD="nrf9161dk"\nCONFIG_BOARD_TARGET="nrf9161dk/nrf9161/ns"\n'
        "CONFIG_UART_CONSOLE=y\nCONFIG_LOG_MODE_DEFERRED=y\nCONFIG_FLASH_SIZE=1024\n"
        "CONFIG_SRAM_SIZE=256\n"
    )
    shutil.copy(DATA / "shell_arm.elf", build / "zephyr" / "zephyr.elf")
    (build / "CMakeCache.txt").write_text(f"APPLICATION_SOURCE_DIR:PATH={src}\n")
    (build / "partitions.yml").write_text(PARTITIONS)
    return src, build


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_describe_build(app):
    _src, build = app
    info = describe_build(build)
    assert info["board"] == "nrf9161dk/nrf9161/ns"
    assert info["kconfig"]["CONFIG_LOG_MODE_DEFERRED"] == "y"
    assert info["memory"]["flash_bytes"] == 534 and info["memory"]["flash_size_kib"] == 1024
    assert info["memory"]["largest_ram"][0] == {"symbol": "keep", "bytes": 24}
    assert [p["name"] for p in info["partitions"]] == ["mcuboot", "app"]
    assert info["app_git"]["dirty"] is False and len(info["app_git"]["commit"]) == 40
    assert any("deferred" in w for w in info["warnings"])
    assert any("CONFIG_ASSERT" in w for w in info["warnings"])


def test_partitions_parser(tmp_path):
    f = tmp_path / "partitions.yml"
    f.write_text(PARTITIONS)
    assert parse_partitions(f)[0] == {
        "name": "mcuboot",
        "address": "0x0",
        "size": 0x8000,
        "region": "flash_primary",
    }


def test_test_names():
    assert named_tests(["west", "twister", "-T", "tests/ble", "-s", "x.y"]) == ["tests/ble", "x.y"]
    assert named_tests(["pytest", "tests/hw", "-v"]) == ["tests/hw"]


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
async def test_last_good_shows_what_changed(arb, app):
    src, build = app
    s, tok = await lease_for(arb)
    res = await done(arb, await arb.flash(s, tok, str(build)))
    assert res["status"] == "done"
    hist = arb.history_query(board="sim-1")["entries"]
    assert hist[0]["kind"] == "flash" and hist[0]["verdict"] == "booted" and hist[0]["ok"]

    # change the app and its config, then ask what changed since it last worked
    (src / "main.c").write_text("int main(void) { return 1; }\n")
    git(src, "commit", "-qam", "second")
    cfg = build / "zephyr" / ".config"
    cfg.write_text(cfg.read_text().replace("CONFIG_LOG_MODE_DEFERRED=y", "CONFIG_ASSERT=y"))
    res = await arb.last_good(build_dir=str(build))
    assert res["found"] and res["entry"]["id"] == hist[0]["id"]
    assert res["since"]["kconfig"]["added"] == {"CONFIG_ASSERT": "y"}
    assert res["since"]["kconfig"]["removed"] == {"CONFIG_LOG_MODE_DEFERRED": "y"}
    assert res["since"]["git"]["commits"] == 1
    assert res["since"]["git"]["files_changed"][0]["file"] == "main.c"


async def test_test_runs_are_recorded(arb, tmp_path):
    s, tok = await lease_for(arb)
    cmd = [sys.executable, "-c", "print('PROJECT EXECUTION SUCCESSFUL')", "-T", "tests/smoke"]
    res = await done(arb, await arb.run(s, tok, cmd, cwd=str(tmp_path)))
    assert res["status"] == "done", res
    good = await arb.last_good(test="tests/smoke")
    assert good["found"] and good["entry"]["tests"] == ["tests/smoke"]
    assert (await arb.last_good(test="tests/other"))["found"] is False


def test_dts_partitions_parser(tmp_path):
    f = tmp_path / "zephyr.dts"
    f.write_text(DTS)
    parts, code = parse_dts_partitions(f)
    assert code == "slot0_ns_partition"
    by_name = {p["name"]: p for p in parts}
    assert list(by_name) == [
        "boot_partition",
        "slot0_partition",
        "slot0_s_partition",
        "slot0_ns_partition",
        "storage_partition",
    ]
    assert by_name["slot0_ns_partition"] == {
        "name": "slot0_ns_partition",
        "label": "image-0-nonsecure",
        "address": "0x50000",  # nested: offset by slot0_partition at 0x10000
        "size": 0x30000,
    }


@pytest.mark.skipif(not shutil.which("git"), reason="needs git")
def test_describe_build_uses_dts_partitions(app):
    """NCS v3.x without Partition Manager: the layout and the slot size come from zephyr.dts."""
    _src, build = app
    (build / "partitions.yml").unlink()
    (build / "zephyr" / "zephyr.dts").write_text(DTS)
    info = describe_build(build)
    assert "slot0_ns_partition" in [p["name"] for p in info["partitions"]]
    mem = info["memory"]
    assert mem["code_partition"] == "slot0_ns_partition" and mem["code_partition_kib"] == 192
    assert mem["flash_used_pct"] == round(100 * 534 / 0x30000, 1)

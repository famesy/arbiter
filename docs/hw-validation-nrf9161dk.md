# arbiter hardware validation on nRF9161 DK

Date: 2026-10-08. Host: Fame's Windows 11 Home PC (10.0.26300).
Scope: check arbiter's hardware assumptions on a real nRF9161 DK. This does not build arbiter itself.
No `recover` was run and nothing was erased. The modem firmware was not touched.

## Toolchain

| Item | Value |
|---|---|
| nRF Connect SDK | v3.4.1 at `C:\ncs\v3.4.1` (Zephyr v4.4.2, MCUboot v2.3.0-dev, TF-M v2.3.1) |
| Toolchain bundle | `C:\ncs\toolchains\4f5b6ad6dd` (Zephyr SDK 1.0.1, arm-zephyr-eabi-gcc 14.3.0, CMake 4.2.1, Ninja 1.13.2, Python 3.12.4) |
| west | v1.5.0 |
| nrfutil | 8.1.1 with `device` 2.20.0. It lives in the bundle, and `NRFUTIL_HOME` points to `nrfutil\home` |
| SEGGER J-Link | V9.82 at `C:\Program Files\SEGGER\JLink_V982` |
| Python libs (bundle) | pylink 1.7.0, pyserial 3.5, intelhex |

**Gotcha: nothing NCS-related is on the system PATH.** `west`, `nrfutil`, `cmake` and the compiler are only reachable after loading the bundle's `environment.json`, which sets PATH, PYTHONPATH, NRFUTIL_HOME, ZEPHYR_TOOLCHAIN_VARIANT and ZEPHYR_SDK_INSTALL_DIR. The SEGGER folder is not on PATH either. The `jlink` that *is* on PATH is Java's `jlink.exe` from Android Studio. arbiter should resolve tools from the toolchain bundle or from absolute SEGGER paths, never from a bare `jlink` or `JLinkExe`. On Windows the J-Link binary is named `JLink.exe`, not `JLinkExe`.

## Probe and serial ports

| Item | Value |
|---|---|
| Probe | J-Link OB-nRF5340-NordicSemi, board PCA10153 (nRF9161 DK v0.9.0) |
| J-Link serial | `1050978819` |
| USB iSerial | `001050978819` (same number, zero-padded to 12 digits) |
| USB VID:PID | 1366:1069 |
| VCOM0 | COM3, application UART (`uart0`, the Zephyr console) |
| VCOM1 | COM4, TF-M secure UART (`uart1`) |
| nrfutil traits | boardController, devkit, jlink, modem, seggerUsb, serialPorts, usb |

Findings:
- **Serial numbers need normalizing.** USB/PnP reports `001050978819`, while J-Link and nrfutil report `1050978819`. arbiter should strip leading zeros, or compare the two as integers.
- **The COM-port mapping is only reliable through `nrfutil device list`, which reports `vcom: 0/1`.** Windows names both ports "JLink CDC UART Port". The interface number (MI_00 maps to VCOM0, MI_02 to VCOM1) also works.
- **Enumeration was briefly incomplete right after plug-in or driver install.** The first `nrfutil device list` found 0 devices, and the MI_02 CDC interface showed `CM_PROB_NOT_CONFIGURED`. A minute later both COM ports were up and nrfutil saw the board. arbiter's probe discovery should retry and not treat a first empty result as "no board".

## Builds (`zephyr/samples/hello_world`, `nrf9161dk/nrf9161/ns`, sysbuild)

| Variant | Command extras | Result |
|---|---|---|
| UART | none | built |
| RTT | `-S rtt-console` | built |
| UART + MCUboot | `-- -DSB_CONFIG_BOOTLOADER_MCUBOOT=y` | built |
| RTT + MCUboot | `-S rtt-console -- -DSB_CONFIG_BOOTLOADER_MCUBOOT=y` | built |

**Gotcha: TF-M rejects a build directory longer than 90 characters** ("CMAKE_BINARY_DIR path length (133) exceeds 90 characters"). The first build in a deep temp path failed for this reason. arbiter's build dirs on Windows must stay short (these builds used `C:\ncs\tmp\arb\<variant>`).

## Console detection signals

With sysbuild, the app's config is at `<build>/<default-image>/zephyr/.config`. **`<build>/zephyr/.config` also exists, but it is the sysbuild config (SB_CONFIG_* only) and contains no console symbols.** arbiter must read `domains.yaml`, take `default:` (here `hello_world`), and look in that image's directory. The ELF is likewise at `<build>/hello_world/zephyr/zephyr.elf`.

| Signal | UART build | RTT build |
|---|---|---|
| `CONFIG_UART_CONSOLE` | `y` | **`y` (still on)** |
| `CONFIG_RTT_CONSOLE` | not set | `y` |
| `CONFIG_USE_SEGGER_RTT` | not set | `y` |
| `_SEGGER_RTT` in zephyr.elf | absent (only the `CONFIG_HAS_SEGGER_RTT` absolute symbol) | `0x20020410`, in `.bss` (`B`) |
| chosen `zephyr,console` | `&uart0` | `&uart0` (the snippet does not change it) |

Findings:
- **The `rtt-console` snippet leaves `CONFIG_UART_CONSOLE=y` enabled**, so the RTT build has both consoles on. On hardware, the UART console wins in that case (see "What this changes about detection" below). The planned "RTT first" order would therefore pick RTT for a build whose output actually goes to UART.
- `nm` matching must be exact on `_SEGGER_RTT`, because `CONFIG_HAS_SEGGER_RTT` shows up as an absolute symbol (`A`) in every nRF build. A substring match on "SEGGER_RTT" gives false positives.
- **Snippets apply to every sysbuild image.** With MCUboot, the `mcuboot` image also got `CONFIG_RTT_CONSOLE=y`. This is one more reason to read only the default image's `.config`.

## Flashing and console output

### Flash layout trap
In NCS v3.4.1, `nrf9161dk/nrf9161/ns` with no bootloader (`SB_CONFIG_BOOTLOADER_NONE=y`) puts TF-M at **0x10000**. It reserves 0x0–0x10000 as the `mcuboot` partition and writes nothing there. `west flash` (nrfutil runner) only erases address ranges the image touches. The DK already held an older firmware at 0x0 (a `coexole_fixture` RTT shell printing heartbeats), so after a successful, verified flash the CPU still booted that old image. COM3 and COM4 were silent. A read-back over J-Link confirmed that the flash matched `tfm_merged.hex`.

Implications for arbiter: a "flashed OK" result does not mean the new image is running. On ns targets without MCUboot, either flash with MCUboot (sysbuild) or erase, and verify by watching for the expected console output rather than trusting the flash exit code.

With Fame's OK, the board was reflashed with the MCUboot variant. This overwrote the old fixture image.

### UART + MCUboot: confirmed
`west flash -d <build> --dev-id 1050978819` flashed `mcuboot` and then `hello_world` (`zephyr.signed.hex`) in about 15 s. west warns that runner options for multiple domains are experimental, which is harmless here.

COM3 (VCOM0, 115200 8N1):
```
*** Booting MCUboot v2.3.0-dev-8122be0de002 ***
...
I: Bootloader chainload address offset: 0x10000
I: Jumping to the first image slot*** Booting nRF Connect SDK v3.4.1-b20f8619ba9a ***
*** Using Zephyr OS v4.4.2-33fa6a7aac6a ***
Hello World! nrf9161dk@0.9.0/nrf9161/ns
```
COM4 (VCOM1) carries TF-M's secure log:
```
[INF] Writing random Hardware Unique Keys to the KMU.
[NOT] Booting TF-M v2.3.1
Creating an empty ITS flash layout.
```
So an ns console tap must listen on **VCOM0**, and VCOM1 is TF-M noise. MCUboot also prints on VCOM0 ahead of the app banner.

### RTT + MCUboot (`-S rtt-console`): the output still goes to UART
Fame approved this flash on 2026-10-09. The build had `CONFIG_RTT_CONSOLE=y` and `CONFIG_UART_CONSOLE=y`, and `_SEGGER_RTT` was at 0x20020410.
- COM3 printed the full `Hello World! nrf9161dk@0.9.0/nrf9161/ns`, the same as the UART build.
- The RTT control block was valid ("SEGGER RTT", 3 up and 3 down buffers, up[0] "Terminal" of 1024 bytes), but **WrOff = 0**, so nothing was ever written to RTT.

Both console drivers install a printk/stdout hook, and the UART console's hook wins. **In NCS v3.4.1 the stock `rtt-console` snippet does not actually move the console to RTT on this board while UART_CONSOLE stays on.**

### RTT-only + MCUboot (`-S rtt-console -Dhello_world_CONFIG_UART_CONSOLE=n`): RTT confirmed
- COM3 shows MCUboot's log only. The app banner is absent from UART. MCUboot got the snippet too, but kept UART_CONSOLE, so its log stayed on UART.
- RTT up[0], read over pylink (J-Link DLL V9.82, SWD at 4000 kHz, device `nRF9161_xxCA`, without halting):
```
*** Booting nRF Connect SDK v3.4.1-b20f8619ba9a ***
*** Using Zephyr OS v4.4.2-33fa6a7aac6a ***
Hello World! nrf9161dk@0.9.0/nrf9161/ns
```
- After a reset, the reader saw the previous run's text again before the new banner, because RTT RAM survives a soft reset. An RTT tap that attaches after a reset can therefore read stale output.

### What this changes about detection
`CONFIG_RTT_CONSOLE=y` alone does **not** mean the console is on RTT. Observed behavior:

| RTT_CONSOLE | UART_CONSOLE | Where the app console actually went |
|---|---|---|
| n | y | UART (VCOM0) |
| y | y | **UART (VCOM0)**, with RTT empty |
| y | n | RTT up[0] |

So "RTT first, then UART" is wrong as a plain precedence rule. The rule that matches the hardware is: **RTT only if `CONFIG_RTT_CONSOLE=y` and `CONFIG_UART_CONSOLE` is not set; otherwise UART if `CONFIG_UART_CONSOLE=y`.** When both are set, arbiter could listen on both ports or warn the user.

## Summary for arbiter's design

1. **Revise the detection order.** Pick RTT only when `CONFIG_RTT_CONSOLE=y` and `CONFIG_UART_CONSOLE` is not set. When both are set, the output goes to UART (verified on hardware). Consider listening on both, or warning, in that case.
1b. An RTT tap should account for stale text left in the buffer after a reset (RTT RAM survives a soft reset).
2. Read `.config` and `zephyr.elf` from the default sysbuild image (`domains.yaml`), not from `<build>/zephyr/`.
3. Match `_SEGGER_RTT` exactly, and ignore the `CONFIG_HAS_SEGGER_RTT` absolute symbol.
4. Normalize probe serials (strip leading zeros). Map VCOM by nrfutil's `vcom` index, not by COM number.
5. On nRF91 ns, VCOM0 is the app console and VCOM1 is TF-M.
6. Don't treat a successful flash as proof of boot. Confirm by console output, and watch for stale images at 0x0 on ns builds without a bootloader.
7. Resolve tools from the NCS toolchain bundle. A bare `jlink` on PATH may be Java's.
8. Keep build dirs short on Windows (TF-M limit is 90 characters).
9. Retry probe enumeration, because the first scan after plug-in or driver install can be empty.

// Made-up but realistic data: Fame's nRF9161 DK held by an agent, a simulated board
// that's free, and an STM32 that's offline. Shared by the stories.
import { BootBlock, Button, BoardActions, HolderRow, type BoardCardProps, type ChipProps, type TermLineInput } from "../src/index.js";

export const boards: BoardCardProps[] = [
  { id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, line: <><b>claude: lte test</b> · 12m 40s · 1 waiting</> },
  { id: "sim-1", state: "available", status: { text: "free", tone: "free" }, line: "native_sim/native/64", lineClass: "muted mono" },
  { id: "nucleo-h743", state: "offline", level: "err", status: { text: "offline", tone: "err" }, line: "Offline: probe not found", lineLevel: "err" },
  { id: "nrf5340dk-1", state: "human", status: { text: "held by Fame", tone: "busy" }, line: <b>Fame</b> },
  { id: "nrf52840dk-1", state: "maintenance", status: { text: "maintenance", tone: "" }, line: "nrf52840dk/nrf52840", lineClass: "muted mono" },
];

export const chips = (tests = "passed"): ChipProps[] => [
  { label: "Queue", value: "1", tone: "on" },
  { label: "Power", value: "3.70 V" },
  { label: "Tests", value: tests, tone: tests === "failed" ? "err" : "ok" },
  { label: "Activity" },
];

export const leasedActions = (
  <BoardActions main={<Button label="Pause agent" variant="primary" />}
    more={[<Button key="t" label="Take over" />, <Button key="x" label="+15 min" />, <Button key="r" label="Revoke lease" variant="danger" />, <Button key="s" label="Reset" disabled />]} />
);

export const leasedHolder = <HolderRow holder="claude: lte test" left="12m 40s" op="test · 1m 05s" reason="run the LTE link tests after the modem fix" />;

export const termLines: TermLineInput[] = [
  <BootBlock summary="Booted Zephyr OS v4.1.99-ncs1 (14 lines)" lines={[
    { text: "*** Booting nRF Connect SDK v3.4.1-9f2a1c4 ***" },
    { text: "*** Using Zephyr OS v4.1.99-ncs1 ***" },
    { text: "Attempting to boot slot 0." },
  ]} />,
  { timestamp: "[00:00:00.251,342] ", text: "<inf> lte_test: Starting LTE link tests" },
  { timestamp: "[00:00:01.004,120] ", text: "<inf> lte_lc: Network registration status: searching" },
  { timestamp: "[00:00:04.518,903] ", text: "<wrn> lte_lc: PSM not granted by the network", kind: "w" },
  { kind: "a", sender: "[claude-1a2b]", text: "> at AT+CEREG?" },
  { text: "+CEREG: 5,1,\"0B2C\",\"01A2D101\",7" },
  { text: "OK" },
  { kind: "h", sender: "[you]", mine: true, text: "> kernel uptime" },
  { prompt: "uart:~$ ", text: "Uptime: 6420 ms" },
  { timestamp: "[00:00:07.880,442] ", text: "<err> lte_test: socket connect failed: -116", kind: "e" },
  { kind: "d", text: "[arbiter] test run finished: 11 passed, 1 failed" },
  { prompt: "uart:~$ ", bare: true },
];

export const channels = [
  { id: "all", label: "All", title: "Every channel, tagged" },
  { id: "uart:app", label: "uart:app", note: "primary" },
  { id: "rtt", label: "rtt" },
];

export const noop = () => {};

export const queue = [
  { who: "codex: fota", reason: "flash the FOTA image and check the version", priority: "normal" as const, waiting: "3m 12s", onDown: noop, onUrgent: noop, onRemove: noop },
  { who: "claude: power test", reason: "wants nrf9161dk", priority: "high" as const, front: true, waiting: "1m 40s", onUp: noop, onUrgent: noop, onRemove: noop },
  { who: "claude: hotfix", reason: "a crash on boot", priority: "urgent" as const, urgent: true, waiting: "20s", onUp: noop, onRemove: noop },
];

export const history = Array.from({ length: 24 }, (_, i) => ({ avg: 900 + 300 * Math.sin(i / 3) + i * 20, peak: 2400 + 900 * Math.cos(i / 4) }));

export const runs = [
  { started: "09:41:12", agent: "claude: lte test", result: { text: "running…", tone: "" as const }, time: "1m 05s" },
  { started: "09:30:02", agent: "claude: lte test", result: { text: "11 passed, 1 failed", tone: "err" as const }, failed: true, time: "2m 41s",
    logPath: "logs/twister-0930.log", junit: "twister-out/twister_report.xml", tail: ["START - test_lte_connect", " FAIL - test_lte_connect in 30.004 seconds", "TESTSUITE lte_link failed."] },
  { started: "09:12:44", agent: "codex: fota", result: { text: "passed", tone: "free" as const }, time: "48s" },
];

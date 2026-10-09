// Made-up but realistic data for the stories: Fame's nRF9161 DK held by an agent, a
// simulated board that's free, and an STM32 that's offline.
import { BoardActions, Button, HolderRow, TermLine, BootBlock, h } from "../index.js";

export const boards = [
  { id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, line: [h("b", {}, "claude: lte test"), " · 12m 40s · 1 waiting"], holder: "claude: lte test", left: "12m 40s" },
  { id: "sim-1", state: "available", status: { text: "free", tone: "free" }, line: "native_sim/native/64", lineClass: "muted mono" },
  { id: "nucleo-h743", state: "offline", level: "err", status: { text: "offline", tone: "err" }, line: "Offline: probe not found", lineLevel: "err" },
  { id: "nrf5340dk-1", state: "human", status: { text: "held by Fame", tone: "busy" }, line: [h("b", {}, "Fame")] },
  { id: "nrf52840dk-1", state: "maintenance", status: { text: "maintenance", tone: "" }, line: "nrf52840dk/nrf52840", lineClass: "muted mono" },
];

export const chips = (over = {}) => [
  { label: "Queue", value: "1", tone: "on" },
  { label: "Power", value: "3.70 V" },
  { label: "Tests", value: over.tests || "passed", tone: over.tests === "failed" ? "err" : "ok" },
  { label: "Activity" },
];

export const leasedActions = () => BoardActions({
  main: Button({ label: "Pause agent", variant: "primary" }),
  more: [Button({ label: "Take over" }), Button({ label: "+15 min" }), Button({ label: "Revoke lease", variant: "danger" }), Button({ label: "Reset", disabled: true })],
});

export const leasedHolder = () => HolderRow({ holder: "claude: lte test", left: "12m 40s", op: "test · 1m 05s", reason: "run the LTE link tests after the modem fix" });

export const termLines = () => [
  BootBlock({ summary: "Booted Zephyr OS v4.1.99-ncs1 (14 lines)", lines: [
    { text: "*** Booting nRF Connect SDK v3.4.1-9f2a1c4 ***" },
    { text: "*** Using Zephyr OS v4.1.99-ncs1 ***" },
    { text: "Attempting to boot slot 0." },
  ] }),
  TermLine({ timestamp: "[00:00:00.251,342] ", text: "<inf> lte_test: Starting LTE link tests" }),
  TermLine({ timestamp: "[00:00:01.004,120] ", text: "<inf> lte_lc: Network registration status: searching" }),
  TermLine({ timestamp: "[00:00:04.518,903] ", text: "<wrn> lte_lc: PSM not granted by the network", kind: "w" }),
  TermLine({ kind: "a", sender: "[claude-1a2b]", text: "> at AT+CEREG?" }),
  TermLine({ text: "+CEREG: 5,1,\"0B2C\",\"01A2D101\",7" }),
  TermLine({ text: "OK" }),
  TermLine({ kind: "h", sender: "[you]", mine: true, text: "> kernel uptime" }),
  TermLine({ prompt: "uart:~$ ", text: "Uptime: 6420 ms" }),
  TermLine({ timestamp: "[00:00:07.880,442] ", text: "<err> lte_test: socket connect failed: -116", kind: "e" }),
  TermLine({ kind: "d", text: "[arbiter] test run finished: 11 passed, 1 failed" }),
  TermLine({ prompt: "uart:~$ ", bare: true }),
];

import { Sheet, QueueTable, PowerPanel, TestRunsTable, EventRow, StatStrip, Sparkline, Check, Button, KV, h } from "../index.js";

export default { title: "Components/Panels" };

const queue = [
  { who: "codex: fota", reason: "flash the FOTA image and check the version", priority: "normal", waiting: "3m 12s", onDown: () => {}, onUrgent: () => {}, onRemove: () => {} },
  { who: "claude: power test", reason: "wants nrf9161dk", priority: "high", front: true, waiting: "1m 40s", onUp: () => {}, onUrgent: () => {}, onRemove: () => {} },
  { who: "claude: hotfix", reason: "a crash on boot", priority: "urgent", urgent: true, waiting: "20s", onUp: () => {}, onRemove: () => {} },
];

const hist = Array.from({ length: 24 }, (_, i) => ({ avg: 900 + 300 * Math.sin(i / 3) + i * 20, peak: 2400 + 900 * Math.cos(i / 4) }));

const power = (over = {}) => PowerPanel({
  on: true, volts: "3.70 V", range: "safe range 3.0–4.2 V",
  controls: [Button({ label: "On", disabled: true }), Button({ label: "Off" }), Button({ label: "Cycle" }), h("span", { class: "sep" }),
    h("input", { type: "number", value: "3700", "aria-label": "Voltage in millivolts" }), h("span", { class: "muted" }, "mV"), Button({ label: "Set voltage" })],
  stats: { stats: [["Average", "1.12 mA"], ["Peak", "3.30 mA"], ["Min", "4.2 µA"], ["Window", "5.0 s"]] },
  history: { points: hist, caption: "Last 24 measurements · solid average, dashed peak · top 3.30 mA" },
  ...over,
});

const runs = [
  { started: "09:41:12", agent: "claude: lte test", result: { text: "running…", tone: "" }, time: "1m 05s" },
  { started: "09:30:02", agent: "claude: lte test", result: { text: "11 passed, 1 failed", tone: "err" }, failed: true, time: "2m 41s", logPath: "logs/twister-0930.log", junit: "twister-out/twister_report.xml",
    tail: ["START - test_lte_connect", " FAIL - test_lte_connect in 30.004 seconds", "TESTSUITE lte_link failed."] },
  { started: "09:12:44", agent: "codex: fota", result: { text: "passed", tone: "free" }, time: "48s" },
];

export const Queue = { render: () => h("div", { class: "card scroll-x", style: "max-width:760px" }, QueueTable({ rows: queue })) };
export const QueueEmpty = { render: () => h("div", { class: "card" }, QueueTable({ rows: [] })) };

export const Power = { render: () => h("div", { class: "card", style: "max-width:760px" }, power()) };
export const PowerLocked = { render: () => h("div", { class: "card", style: "max-width:760px" }, power({ locked: true })) };
export const PowerOff = { render: () => h("div", { class: "card", style: "max-width:760px" }, power({ on: false, volts: null, stats: null, history: null, empty: "No current measurement yet. Agents measure with measure_current." })) };
export const PowerFault = { render: () => h("div", { class: "card", style: "max-width:760px" }, power({ fault: "over current (52 mA > 50 mA)", stats: { warn: true, stats: [["Average", "51.2 mA"], ["Peak", "58.0 mA"]], note: [h("b", {}, "Not a valid measurement: "), "a debugger was attached"] } })) };

export const Measurements = {
  render: () => h("div", { class: "card", style: "max-width:760px" },
    StatStrip({ stats: [["Average", "1.12 mA"], ["Peak", "3.30 mA"], ["Min", "4.2 µA"], ["Window", "5.0 s"]] }),
    Sparkline({ points: hist, caption: "Last 24 measurements · solid average, dashed peak · top 3.30 mA" })),
};

export const TestRuns = { render: () => h("div", { class: "card scroll-x", style: "max-width:760px" }, TestRunsTable({ rows: runs })) };

export const Activity = {
  render: () => h("div", { class: "card", style: "max-width:760px" }, h("div", { id: "activity" },
    Check({ label: "Selected board only" }),
    h("div", { id: "feed" },
      EventRow({ time: "09:41:12", text: "claude: lte test started test on nrf9161dk-1" }),
      EventRow({ time: "09:40:58", text: "Fame sent “kernel uptime” to nrf9161dk-1" }),
      EventRow({ time: "09:39:30", text: "nrf9161dk-1 flash: ok, boot not seen (14s)", level: "warn" }),
      EventRow({ time: "09:33:02", text: "claude: lte test test on nrf9161dk-1: 11 passed, 1 failed (2m 41s)", level: "err" }),
      EventRow({ time: "09:30:00", text: "claude: lte test got nrf9161dk-1: run the LTE link tests" })))),
};

export const SheetDialog = {
  render: () => h("div", { style: "min-height:520px;padding-top:24px" }, Sheet({ open: true, title: "Queue", children: QueueTable({ rows: queue }) })),
};

export const InfoSheet = {
  render: () => h("div", { style: "min-height:420px;padding-top:24px" }, Sheet({ open: true, title: "nrf9161dk-1", children: KV({ rows: [
    ["Platform", h("span", { class: "mono" }, "nrf9161dk/nrf9161/ns")], ["Probe", h("span", { class: "mono" }, "1050978819")],
    ["Console", "UART (.config)"], ["Last flash", "boot confirmed"], ["Shell", "48 commands"], ["Tags", "lte, modem"],
  ] }) })),
};

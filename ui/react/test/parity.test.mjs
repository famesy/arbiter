// The React components must render exactly what the plain ones do, so app.css styles
// both the same and Claude Design's previews match the real dashboard. Each case renders
// the plain component into a DOM and the React one to static markup, and compares the two
// after normalising what can't matter (attribute order, empty class, <tbody>).
import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const window = new Window();
globalThis.document = window.document;
globalThis.Node = window.Node;

const plain = await import("../../../backend/arbiter/dashboard/components/index.js");
const react = await import("../dist/index.js");

/** One implementation: make(name, props) builds a component, text(s) a string child. */
const PLAIN = { make: (name, props) => plain[name](props), b: (s) => plain.h("b", {}, s) };
const REACT = { make: (name, props) => createElement(react[name], props), b: (s) => createElement("b", null, s) };

function canon(node) {
  if (node.nodeType === 3) return node.textContent;
  if (node.nodeType !== 1) return "";
  const tag = node.tagName.toLowerCase();
  const kids = [...node.childNodes].map(canon).join("");
  if (tag === "tbody") return kids;
  const attrs = [...node.attributes]
    .map((a) => [a.name, a.name === "class" ? a.value.split(/\s+/).filter(Boolean).sort().join(" ")
      : a.name === "style" ? a.value.replace(/\s+/g, "").replace(/;$/, "") : a.value])
    .filter(([n, v]) => !(n === "class" && v === ""))
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([n, v]) => ` ${n}="${v}"`).join("");
  return `<${tag}${attrs}>${kids}</${tag}>`;
}

function renderPlain(name, props) {
  const out = plain[name](props);
  const box = document.createElement("div");
  box.append(...(Array.isArray(out) ? out : [out]));
  return [...box.childNodes].map(canon).join("");
}

function renderReact(name, props) {
  const html = renderToStaticMarkup(createElement(react[name], props));
  // A bare <tr> only parses inside a table.
  const box = document.createElement(html.startsWith("<tr") ? "tbody" : "div");
  if (html.startsWith("<tr")) document.createElement("table").append(box);
  box.innerHTML = html;
  return [...box.childNodes].map(canon).join("");
}

const line = [{ timestamp: "[00:00:00.251] ", text: "<inf> lte_test: start" }, { kind: "w", text: "<wrn> PSM not granted" },
  { kind: "a", sender: "[claude-1a2b]", text: "> at AT+CEREG?" }, { kind: "h", sender: "[you]", mine: true, text: "> kernel uptime" },
  { prompt: "uart:~$ ", bare: true }, {}];

// [component, props(impl)]. Props are a function so element-valued props are built by
// the same implementation that renders them.
const CASES = [
  ["Logo", () => ({})],
  ["Brand", () => ({})],
  ["Brand", () => ({ as: "h1" })],
  ["Button", () => ({ label: "Pause agent", variant: "primary" })],
  ["Button", () => ({ label: "×", size: "icon", "aria-label": "Close", title: "Close" })],
  ["Button", () => ({ label: "Reset", disabled: true })],
  ["ButtonRow", (I) => ({ items: [I.make("Button", { label: "A" }), "sep", I.make("Button", { label: "B", variant: "danger" })] })],
  ["Menu", (I) => ({ label: "⋯", id: "more", ariaLabel: "More", open: true, items: [I.make("Button", { label: "Pause all agents" })] })],
  ["CheckMenu", () => ({ options: [{ id: "fold", label: "Fold boot output", checked: true }, { id: "ts", label: "Show log timestamps" }] })],
  ["Tabs", () => ({ items: [{ id: "all", label: "All", title: "Every channel" }, { id: "uart:app", label: "uart:app", note: "primary" }], active: "all" })],
  ["NavTabs", () => ({ items: [{ id: "dash", label: "Dashboard" }, { id: "settings", label: "Settings", href: "#settings" }], active: "dash" })],
  ["Switch", () => ({ checked: true, label: "Sounds" })],
  ["Switch", () => ({})],
  ["ToggleRow", () => ({ label: "Fold boot output", hint: "Shows one line per boot.", checked: true })],
  ["Check", () => ({ label: "Selected board only", id: "feed-sel", checked: true })],
  ["Pill", () => ({ text: "testing", tone: "busy" })],
  ["Pill", () => ({ text: "free", tone: "free", dot: false })],
  ["ConnPill", () => ({ up: true })],
  ["ConnPill", () => ({ up: false })],
  ["Tag", () => ({ text: "after restart", restart: true })],
  ["Alert", (I) => ({ level: "warn", text: [I.b("codex: fota"), " asks to erase"], actions: [I.make("Button", { label: "Approve", variant: "primary" })] })],
  ["Alert", () => ({ level: "note", text: "Nothing to approve." })],
  ["Issue", () => ({ text: "Boot failed", level: "err" })],
  ["Toast", () => ({ text: "Saved", level: "" })],
  ["Empty", () => ({ text: "No boards yet." })],
  ["BoardCard", () => ({ id: "sim-1", line: "native_sim/native/64", lineClass: "muted mono" })],
  ["BoardCard", (I) => ({ id: "nrf9161dk-1", state: "leased", selected: true, status: { text: "testing", tone: "busy" }, line: [I.b("claude"), " · 12m"] })],
  ["BoardCard", () => ({ id: "nucleo-h743", state: "offline", level: "err", status: { text: "offline", tone: "err" }, line: "Offline", lineLevel: "err" })],
  ["ProbeChip", () => ({ count: 2 })],
  ["AgentRow", () => ({ label: "claude: lte test", dot: "on", what: "nrf9161dk-1", title: "claude-code" })],
  ["AgentRow", () => ({ label: "codex: fota" })],
  ["HolderRow", () => ({ holder: "claude: lte test", left: "12m 40s", op: "test · 1m 05s", reason: "run the LTE tests" })],
  ["HolderRow", () => ({ holder: "Fame", paused: true, left: "on hold" })],
  ["HolderRow", () => ({ platform: "native_sim/native/64" })],
  ["Chip", () => ({ label: "Power", value: "3.70 V", tone: "ok" })],
  ["ChipStrip", () => ({ chips: [{ label: "Queue", value: "1", tone: "on" }, { label: "Activity" }] })],
  ["BoardActions", (I) => ({ main: I.make("Button", { label: "Pause agent", variant: "primary" }), more: [I.make("Button", { label: "Take over" })] })],
  ["BoardActions", () => ({})],
  ["BoardBar", (I) => ({ id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" },
    actions: I.make("BoardActions", { main: I.make("Button", { label: "Pause agent", variant: "primary" }) }),
    holder: I.make("HolderRow", { holder: "claude", left: "1m" }), chips: [{ label: "Tests", value: "failed", tone: "err" }],
    issues: [{ text: "Lease ends in 1m", level: "warn" }] })],
  ["KeyValues", () => ({ rows: [["Platform", "nrf9161dk/nrf9161/ns"], null, ["Console", "offline", "err"]] })],
  ["Terminal", () => ({ lines: line })],
  ["Terminal", () => ({ lines: line, view: { fold: false, ts: true, prompt: true }, id: "t2" })],
  ["TermLine", () => ({ source: "[uart:app] ", text: "OK" })],
  ["BootBlock", () => ({ summary: "Booted Zephyr OS (2 lines)", lines: line.slice(0, 2), level: "w", open: true })],
  ["Suggestions", () => ({ options: [{ name: "kernel", help: "Kernel commands\nmore", more: true }, { name: "log" }], active: 1 })],
  ["Suggestions", () => ({})],
  ["CommandBar", () => ({ disabled: true })],
  ["TermCard", (I) => ({ channels: [{ id: "all", label: "All" }], lines: line.slice(0, 2), help: "kernel uptime", hint: [I.b("claude"), " keeps the board"] })],
  ["Sheet", (I) => ({ title: "Queue", open: true, children: I.make("QueueTable", {}) })],
  ["QueueRow", () => ({ position: 1, who: "codex: fota", reason: "flash the FOTA image", priority: "high", front: true, waiting: "4m", onUp: () => {} })],
  ["QueueTable", () => ({ rows: [{ who: "a", urgent: true, priority: "urgent" }, { who: "b" }] })],
  ["Stat", () => ({ label: "Average", value: "12.4 mA" })],
  ["StatStrip", () => ({ stats: [["Average", "12.4 mA"], ["Peak", "180 mA"]], warn: true, note: "Over budget" })],
  ["Sparkline", () => ({ points: [{ avg: 10, peak: 20 }, { avg: 12, peak: 30 }, { avg: 9 }], caption: "Last 10 minutes" })],
  ["PowerPanel", (I) => ({ volts: "3.70 V", range: "safe range 3.0–4.2 V", controls: [I.make("Button", { label: "Off" })], locked: true,
    stats: { stats: [["Average", "12 mA"]] }, history: { points: [{ avg: 1 }, { avg: 2 }] } })],
  ["PowerPanel", () => ({ on: false, fault: "overcurrent", empty: "No readings yet." })],
  ["TestRunRow", () => ({ started: "14:02", agent: "claude", result: { text: "1 failed", tone: "err" }, failed: true, time: "2m", logPath: "/tmp/x.log", junit: "/tmp/j.xml", tail: ["a", "b"] })],
  ["TestRunsTable", () => ({ rows: [{ started: "14:02", agent: "claude", result: { text: "passed", tone: "free" }, time: "1m" }] })],
  ["TestRunsTable", () => ({})],
  ["EventRow", () => ({ time: "14:02", text: "claude took nrf9161dk-1", level: "warn" })],
  ["GuideContent", (I) => ({ steps: ["Welcome", "Boards", "Done"], step: 1, tint: "peach", body: I.b("Hello") })],
  ["GuideContent", () => ({ steps: ["Welcome", "Done"], step: 1, kicker: "Last step" })],
  ["Guide", () => ({ open: true, steps: ["Welcome", "Boards"], step: 0 })],
  ["GuideRow", (I) => ({ name: "1050978819", mono: true, detail: "J-Link", end: I.make("Pill", { text: "new", tone: "busy" }) })],
  ["GuideList", () => ({ rows: [{ name: "sim-1" }, { name: "nrf9161dk-1", detail: "nrf9161dk/nrf9161/ns" }] })],
  ["Tally", () => ({ ok: 9, warn: 1, fail: 0 })],
  ["CmdBox", () => ({ text: "arbiter init" })],
  ["TourItem", () => ({ n: 1, title: "Type into the terminal", text: "Lines you send are marked as yours." })],
  ["Section", (I) => ({ id: "boards", title: "Boards", sub: "Each board's hardware.", children: I.make("Field", { label: "Driver", value: "nrf" }) })],
  ["Field", () => ({ label: "Flash runner", value: "not reported yet", muted: true, hint: "From the build." })],
  ["FieldGroup", (I) => ({ title: "Hardware", children: [I.make("Field", { label: "Platform", value: "nrf9161dk" })] })],
  ["CheckRow", () => ({ status: "WARN", name: "J-Link", detail: "old firmware" })],
  ["CheckRow", () => ({ status: "FAIL", name: "west" })],
  ["BoardSettings", (I) => ({ id: "nrf9161dk-1", pills: [I.make("Pill", { text: "nrf", tone: "free" })], actions: I.make("Button", { label: "Edit" }), editing: true })],
];

for (const [name, props] of CASES) {
  test(`${name} ${JSON.stringify(props(PLAIN), (k, v) => (v instanceof window.Node ? "<el>" : v)).slice(0, 60)}`, () => {
    assert.equal(renderReact(name, props(REACT)), renderPlain(name, props(PLAIN)));
  });
}

test("every plain component has a React twin", () => {
  const helpers = new Set(["h", "fill", "cls", "setTermView"]);
  const missing = Object.keys(plain).filter((k) => !helpers.has(k) && !(k in react));
  assert.deepEqual(missing, []);
});

test("every component is covered by a parity case", () => {
  const covered = new Set(CASES.map(([n]) => n));
  const missing = Object.keys(react).filter((k) => typeof react[k] === "function" && !covered.has(k));
  assert.deepEqual(missing, []);
});

import { Guide, GuideList, GuideRow, Tally, CmdBox, TourItem, CheckRow, Pill, Button, h } from "../index.js";

export default { title: "Components/Getting started guide", parameters: { layout: "fullscreen" } };

const STEPS = ["Boards", "Health check", "Connect agents", "Using the board"];
const TINTS = ["sage", "peach", "lilac", "pink"];
const page = (step, body) => h("div", { style: "min-height:780px;padding-top:24px" }, Guide({ open: true, steps: STEPS, step, tint: TINTS[step], body }));

export const Boards = {
  render: () => page(0, [
    h("p", { class: "lead" }, "arbiter shares your dev boards between AI agents and you. These boards are set up:"),
    GuideList({ rows: [
      { name: "nrf9161dk-1", detail: "nrf9161dk/nrf9161/ns", end: Pill({ text: "free", tone: "free" }) },
      { name: "sim-1", detail: "native_sim/native/64", end: Pill({ text: "in use", tone: "busy" }) },
    ] }),
    h("p", {}, h("b", {}, "1 probe"), " plugged in but not set up:"),
    GuideList({ rows: [GuideRow({ name: "001050978819", mono: true, detail: "jlink", end: Button({ label: "Add", size: "small", variant: "primary" }) })] }),
    h("p", { class: "muted" }, "To detect boards from a terminal instead, run ", h("code", {}, "arbiter init --write"), " and restart arbiterd."),
    h("div", { class: "btn-row" }, Button({ label: "Add a simulated board", size: "small" }), Button({ label: "Open board settings", size: "small" })),
  ]),
};

export const HealthCheck = {
  render: () => page(1, [
    h("p", { class: "lead" }, "Checks the tools, probes and serial ports each board needs. Probes held by an agent are left alone."),
    Tally({ ok: 14, warn: 1, fail: 1 }),
    h("div", { class: "checks" },
      CheckRow({ status: "FAIL", name: "nucleo-h743 · probe", detail: "ST-Link 066DFF not found on USB" }),
      CheckRow({ status: "WARN", name: "nrf9161dk-1 · RTT", detail: "pylink not installed; RTT console unavailable" })),
    Button({ label: "Run again", size: "small" }),
  ]),
};

export const ConnectAgents = {
  render: () => page(2, [
    h("p", { class: "lead" }, "Agents ask arbiter for a board, then flash, test and read the console through it."),
    h("h3", {}, "Claude Code"),
    CmdBox({ text: "/plugin marketplace add famesy/arbiter\n/plugin install arbiter@arbiter" }),
    h("p", { class: "muted" }, "Then run ", h("code", {}, "/arbiter:setup"), " once."),
    h("h3", {}, "Codex"),
    CmdBox({ text: "[mcp_servers.arbiter]\ncommand = \"arbiter\"\nargs = [\"mcp\"]" }),
  ]),
};

export const UsingTheBoard = {
  render: () => page(3, [
    h("p", { class: "lead" }, "Pick a board on the left. Its terminal fills the page."),
    TourItem({ n: 1, title: "Type into the terminal", text: "Lines you send are marked as yours, even while an agent holds the board." }),
    TourItem({ n: 2, title: "Tab suggests shell commands", text: "They come from the flashed image. ↑ recalls earlier lines." }),
    TourItem({ n: 3, title: "Pause or take over", text: "The button next to the board's name. More actions are under Actions." }),
    TourItem({ n: 4, title: "Queue, power and tests", text: "Tap the chips under the terminal for details." }),
  ]),
};

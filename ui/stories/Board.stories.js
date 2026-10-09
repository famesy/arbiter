import { BoardCard, ProbeChip, AgentRow, BoardBar, BoardActions, HolderRow, Chip, ChipStrip, KV, Button, h } from "../index.js";
import { boards, chips, leasedActions, leasedHolder } from "./sample.js";

export default { title: "Components/Board" };

const rail = (...kids) => h("aside", { class: "rail", style: "position:static;width:250px" }, kids);

export const Card = {
  args: { id: "nrf9161dk-1", state: "leased", selected: true },
  argTypes: { state: { control: "select", options: ["available", "leased", "paused", "human", "maintenance", "offline", "needs_recover"] } },
  render: ({ id, state, selected }) => rail(BoardCard({ ...boards[0], id, state, selected })),
};

export const CardsByState = {
  render: () => rail(h("h2", {}, "Boards"), h("div", { id: "boards" }, boards.map((b, i) => BoardCard({ ...b, selected: i === 0 })))),
};

export const Rail = {
  render: () => rail(
    h("h2", {}, "Boards"),
    h("div", { id: "boards" }, boards.slice(0, 3).map((b, i) => BoardCard({ ...b, selected: i === 0 }))),
    ProbeChip({ count: 1 }),
    h("h2", {}, "Agents"),
    h("div", { id: "sessions" },
      AgentRow({ label: "claude: lte test", dot: "on", what: "nrf9161dk-1", title: "claude-code · fix/modem" }),
      AgentRow({ label: "codex: fota", what: "waiting for nrf9161dk-1" }),
      AgentRow({ label: "claude: docs", dot: "warn", what: "not responding" }))),
};

export const BarLeased = {
  render: () => BoardBar({ id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, actions: leasedActions(), holder: leasedHolder(), chips: chips() }),
};

export const BarFree = {
  render: () => BoardBar({
    id: "sim-1", state: "available", status: { text: "free", tone: "free" },
    actions: BoardActions({ main: Button({ label: "Take board", variant: "primary" }), more: [Button({ label: "Reset" }), Button({ label: "Maintenance" })] }),
    holder: HolderRow({ platform: "native_sim/native/64" }),
    chips: [{ label: "Queue", value: "0" }, { label: "Tests", value: "none" }, { label: "Activity" }],
  }),
};

export const BarPaused = {
  render: () => BoardBar({
    id: "nrf9161dk-1", state: "paused", status: { text: "paused", tone: "busy" },
    actions: BoardActions({ main: Button({ label: "Resume agent", variant: "primary" }), more: [Button({ label: "Take over" }), Button({ label: "Revoke lease", variant: "danger" })] }),
    holder: HolderRow({ holder: "claude: lte test", paused: true, left: "on hold" }),
    chips: chips(),
  }),
};

export const BarWithProblems = {
  render: () => BoardBar({
    id: "nrf9161dk-1", state: "leased", level: "err", status: { text: "agent not responding", tone: "warn" },
    actions: leasedActions(),
    holder: HolderRow({ holder: "claude: lte test", left: "ends in 42s" }),
    chips: chips({ tests: "failed" }),
    issues: [{ level: "warn", text: "claude: lte test stopped responding; the lease ends in 42s" }, { level: "err", text: "Last test run failed" }],
  }),
};

export const Chips = {
  render: () => h("div", { style: "display:flex;flex-direction:column;gap:var(--s3)" },
    ChipStrip({ chips: chips() }),
    h("div", { class: "strip" }, Chip({ label: "Power", value: "off", tone: "warn" }), Chip({ label: "Power", value: "fault", tone: "err" }), Chip({ label: "Tests", value: "running" }))),
};

export const Info = {
  render: () => h("div", { class: "card", style: "max-width:520px" }, KV({ rows: [
    ["Platform", h("span", { class: "mono" }, "nrf9161dk/nrf9161/ns")],
    ["Probe", h("span", { class: "mono" }, "1050978819")],
    ["Ports", h("span", { class: "mono" }, "/dev/ttyACM0, /dev/ttyACM1")],
    ["Console", "UART (.config)"],
    ["Last flash", "flashed, boot not seen", "warn"],
    ["Shell", "48 commands"],
    ["Power", "On · 3.70 V"],
  ] })),
};

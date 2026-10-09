import { Brand, ConnPill, NavTabs, Menu, Button, Alert, BoardCard, ProbeChip, AgentRow, BoardBar, TermCard, h } from "../index.js";
import { boards, chips, leasedActions, leasedHolder, termLines } from "./sample.js";

export default { title: "Pages/Dashboard", parameters: { layout: "fullscreen" } };

export const TerminalFirst = {
  render: () => h("div", {},
    h("header", {},
      Brand(), ConnPill({ up: true }), h("span", { class: "spacer" }),
      NavTabs({ items: [{ id: "dash", label: "Dashboard" }, { id: "settings", label: "Settings", href: "#settings" }], active: "dash" }),
      Menu({ id: "more", label: "⋯", ariaLabel: "More", items: [Button({ label: "Pause all agents" }), Button({ label: "Getting started guide" })] })),
    h("div", { class: "wrap" },
      h("div", { id: "alerts" }, Alert({ level: "warn", text: [h("b", {}, "codex: fota"), " asks to erase ", h("b", {}, "nrf9161dk-1")],
        actions: [Button({ label: "Approve", variant: "primary" }), Button({ label: "Deny" })] })),
      h("main", { class: "desk" },
        h("aside", { class: "rail" },
          h("h2", {}, "Boards"),
          h("div", { id: "boards" }, boards.slice(0, 3).map((b, i) => BoardCard({ ...b, selected: i === 0 }))),
          ProbeChip({ count: 1 }),
          h("h2", {}, "Agents"),
          h("div", { id: "sessions" },
            AgentRow({ label: "claude: lte test", dot: "on", what: "nrf9161dk-1" }),
            AgentRow({ label: "codex: fota", what: "waiting for nrf9161dk-1" }))),
        h("section", { id: "detail" },
          BoardBar({ id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, actions: leasedActions(), holder: leasedHolder(), chips: chips() }),
          TermCard({
            channels: [{ id: "all", label: "All" }, { id: "uart:app", label: "uart:app", note: "primary" }],
            lines: termLines(),
            hint: [h("b", {}, "claude: lte test"), " keeps the board; your lines are marked as yours · Tab: 48 shell commands · ↑ history"],
          }))))),
};

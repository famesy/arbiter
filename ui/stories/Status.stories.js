import { Pill, Alert, Issue, Toast, Empty, Button, h } from "../index.js";

export default { title: "Components/Status" };

export const Pills = {
  args: { text: "in use", tone: "busy", dot: true },
  argTypes: { tone: { control: "inline-radio", options: ["", "free", "busy", "warn", "err"] } },
  render: (args) => Pill(args),
};

export const AllPills = {
  render: () => h("div", { class: "btn-row" },
    Pill({ text: "free", tone: "free" }), Pill({ text: "in use", tone: "busy" }), Pill({ text: "flashing", tone: "busy" }),
    Pill({ text: "maintenance" }), Pill({ text: "agent not responding", tone: "warn" }), Pill({ text: "offline", tone: "err" }),
    Pill({ text: "available", tone: "free", dot: false })),
};

export const ApprovalBanner = {
  render: () => Alert({
    level: "warn",
    text: [h("b", {}, "claude: lte test"), " asks to erase ", h("b", {}, "nrf9161dk-1")],
    actions: [Button({ label: "Approve", variant: "primary" }), Button({ label: "Deny" }), Button({ label: "Show board", size: "small" })],
  }),
};

export const Banners = {
  render: () => h("div", { style: "display:flex;flex-direction:column;gap:var(--s2)" },
    Alert({ level: "warn", text: "Restart arbiterd to apply 2 saved changes: boards.nrf9161dk-1.runner, daemon.port." }),
    Alert({ level: "err", text: "nrf9161dk-1 is offline (probe not found)" }),
    Alert({ level: "note", text: ["Saved to ", h("code", {}, "~/.local/state/arbiter/config.toml"), ". Changes marked “applies now” take effect at once."] })),
};

export const BoardIssues = {
  render: () => h("div", { class: "issues", style: "max-width:560px" },
    Issue({ level: "err", text: "Flash failed: west flash exited with 2" }),
    Issue({ level: "warn", text: "Flashed, boot not seen: no banner within 10 s" }),
    Issue({ level: "warn", text: "Powered off" })),
};

export const Toasts = {
  render: () => h("div", { style: "display:flex;flex-direction:column;gap:var(--s2);align-items:flex-start" },
    Toast({ text: "You have nrf9161dk-1. The agent waits at the front of the queue." }),
    Toast({ text: "Saved. 1 change applies after you restart arbiterd.", level: "warn" }),
    Toast({ text: "Send: the board is offline", level: "err" })),
};

export const EmptyState = { render: () => Empty({ text: "Nobody is waiting for this board." }) };

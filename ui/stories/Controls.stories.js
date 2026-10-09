import { Button, ButtonRow, Menu, CheckMenu, Tabs, Switch, ToggleRow, Check, h } from "../index.js";

export default { title: "Components/Controls" };

export const Buttons = {
  args: { label: "Take board", variant: "primary", size: "", disabled: false },
  argTypes: {
    variant: { control: "inline-radio", options: ["", "primary", "danger", "link"] },
    size: { control: "inline-radio", options: ["", "small", "icon"] },
  },
  render: (args) => Button(args),
};

export const AllButtons = {
  render: () => h("div", { style: "display:flex;flex-direction:column;gap:var(--s4)" },
    ButtonRow({ items: [Button({ label: "Pause agent", variant: "primary" }), Button({ label: "Take over" }), Button({ label: "+15 min" }), "sep", Button({ label: "Revoke lease", variant: "danger" })] }),
    ButtonRow({ items: [Button({ label: "Run again", size: "small" }), Button({ label: "Urgent", size: "small" }), Button({ label: "Remove", size: "small", variant: "danger" }), Button({ label: "↑", size: "icon", "aria-label": "Move up" }), Button({ label: "×", size: "icon", "aria-label": "Close" })] }),
    ButtonRow({ items: [Button({ label: "Reset", disabled: true, title: "Pause the agent or take over first" }), Button({ label: "Skip the guide", variant: "link" })] })),
};

export const ActionsMenu = {
  render: () => h("div", { style: "height:220px" }, Menu({ label: "Actions ▾", open: true, items: [
    Button({ label: "Take over" }), Button({ label: "+15 min" }), Button({ label: "Reset", disabled: true }), Button({ label: "Revoke lease", variant: "danger" }),
  ] })),
};

export const ViewMenu = {
  render: () => h("div", { style: "height:180px;display:flex;justify-content:flex-end" }, CheckMenu({ open: true, options: [
    { id: "fold", label: "Fold boot output", checked: true },
    { id: "ts", label: "Show log timestamps", checked: false },
    { id: "prompt", label: "Show shell prompts", checked: false },
  ] })),
};

export const ChannelTabs = {
  args: { active: "all" },
  argTypes: { active: { control: "inline-radio", options: ["all", "uart:app", "rtt"] } },
  render: ({ active }) => Tabs({ active, items: [
    { id: "all", label: "All", title: "Every channel, tagged" },
    { id: "uart:app", label: "uart:app", note: "primary" },
    { id: "rtt", label: "rtt" },
  ] }),
};

export const Switches = {
  render: () => h("div", { class: "card", style: "max-width:520px" },
    ToggleRow({ label: "Fold boot output", hint: "Shows bootloader and banner output as one line you can open.", checked: true }),
    ToggleRow({ label: "Show log timestamps", hint: "Zephyr log times like [00:00:01.234,567]." }),
    h("div", { style: "display:flex;gap:var(--s4);margin-top:var(--s4)" }, Switch({ checked: true, label: "On" }), Switch({ label: "Off" }), Check({ label: "Selected board only" }))),
};

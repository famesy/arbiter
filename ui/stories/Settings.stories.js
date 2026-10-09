import { Section, Field, FieldGroup, CheckRow, BoardSettings, ToggleRow, Pill, Tag, Button, h } from "../index.js";

export default { title: "Components/Settings" };

export const BoardSection = {
  render: () => h("div", { style: "max-width:980px" }, Section({ id: "boards", title: "Boards", sub: "Each board's hardware, console and power.", children: [
    BoardSettings({ id: "nrf9161dk-1", pills: [Pill({ text: "in use", tone: "busy" })], actions: Button({ label: "Edit", size: "small" }), children: h("div", { class: "groups" },
      FieldGroup({ title: "Hardware", children: [Field({ label: "Platform", value: "nrf9161dk/nrf9161/ns" }), Field({ label: "Driver", value: "nrf" }), Field({ label: "Probe serial", value: "1050978819" })] }),
      FieldGroup({ title: "Console", children: [Field({ label: "Mode", value: "auto", hint: "auto picks RTT only when the build has CONFIG_RTT_CONSOLE=y and no UART console." }), Field({ label: "Primary channel", value: "uart:app" })] }),
      FieldGroup({ title: "Power", children: [Field({ label: "Supply", value: "ppk2" }), Field({ label: "Voltage range", value: "3.00 V to 4.20 V", hint: "Refused outside this range, for agents and you alike." })] }),
      FieldGroup({ title: "Agent rules", children: [Field({ label: "Agents may erase", value: "no", hint: "When off, erase and recover ask you first." }), Field({ label: "Flash runner", value: "not reported yet", muted: true })] })) }),
    BoardSettings({ id: "nrf5340dk-1", pills: [Pill({ text: "starts after a restart", tone: "warn" })] }),
  ] })),
};

export const HealthChecks = {
  render: () => h("div", { style: "max-width:980px" }, Section({ id: "health", title: "Health check", sub: "The same checks as arbiter doctor. They read the setup and never touch a board.", children: h("div", { class: "checks" },
    CheckRow({ status: "FAIL", name: "nucleo-h743 · probe", detail: "ST-Link 066DFF not found on USB" }),
    CheckRow({ status: "WARN", name: "nrf9161dk-1 · RTT", detail: "pylink not installed" }),
    CheckRow({ status: "OK", name: "west", detail: "west 1.4.0" }),
    CheckRow({ status: "OK", name: "nrfutil", detail: "nrfutil 7.13.0" })) })),
};

export const Preferences = {
  render: () => h("div", { style: "max-width:720px" }, Section({ id: "prefs", title: "This browser", sub: "Saved in this browser only.", children: h("div", { class: "prefs" },
    h("h3", { style: "margin-top:0" }, "Terminal"),
    ToggleRow({ label: "Fold boot output", hint: "Shows bootloader and banner output as one line you can open.", checked: true }),
    ToggleRow({ label: "Show log timestamps", hint: "Zephyr log times like [00:00:01.234,567]." }),
    h("h3", {}, "Activity and alerts"),
    ToggleRow({ label: "Desktop notifications", hint: "For approvals and warnings while this tab is in the background.", checked: true })) })),
};

export const FieldTags = {
  render: () => h("div", { class: "efield", style: "max-width:320px" }, h("label", { class: "label" }, "Lease length", Tag({ text: "applies now" }), Tag({ text: "after restart", restart: true })), h("input", { type: "number", value: "900" })),
};

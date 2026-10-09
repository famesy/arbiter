import { TermCard, Terminal, TermLine, BootBlock, CommandBar, Suggestions, Button, h } from "../index.js";
import { termLines } from "./sample.js";

export default { title: "Components/Terminal" };

const channels = [
  { id: "all", label: "All", title: "Every channel, tagged" },
  { id: "uart:app", label: "uart:app", note: "primary" },
  { id: "rtt", label: "rtt" },
];

export const Card = {
  render: () => h("div", { style: "max-width:960px" }, TermCard({
    channels, channel: "all", lines: termLines(),
    hint: [h("b", {}, "claude: lte test"), " keeps the board; your lines are marked as yours · Tab: 48 shell commands · ↑ history"],
  })),
};

export const NoCommandHints = {
  render: () => h("div", { style: "max-width:960px" }, TermCard({
    channels, channel: "uart:app", lines: termLines().slice(1, 4),
    hint: "Sends to the uart:app · No command hints: the image was built without CONFIG_SHELL · ↑ history",
  })),
};

export const ViewOptions = {
  args: { fold: true, ts: false, prompt: false },
  render: (view) => h("div", { style: "max-width:960px" }, Terminal({ view, lines: termLines() })),
};

export const BootOutput = {
  render: () => Terminal({ lines: [
    BootBlock({ summary: "Booted Zephyr OS v4.1.99-ncs1 (14 lines)", lines: [{ text: "*** Booting nRF Connect SDK v3.4.1 ***" }] }),
    BootBlock({ summary: "Booted TF-M v2.1.1 (9 lines, has warnings)", level: "w", open: true, lines: [{ text: "[WRN] This device was provisioned with dummy keys.", kind: "w" }, { text: "Booting TF-M v2.1.1" }] }),
    BootBlock({ summary: "Booting (4 lines, has errors)", level: "e", lines: [{ text: "E: Image in the primary slot is not valid!", kind: "e" }] }),
  ] }),
};

export const LineKinds = {
  render: () => Terminal({ view: { fold: true, ts: true, prompt: true }, lines: [
    TermLine({ text: "plain firmware output" }),
    TermLine({ timestamp: "[00:00:01.234,567] ", text: "<inf> app: with a log timestamp" }),
    TermLine({ kind: "w", text: "<wrn> app: a warning" }),
    TermLine({ kind: "e", text: "<err> app: an error" }),
    TermLine({ kind: "d", text: "[arbiter] a note from arbiter" }),
    TermLine({ kind: "h", sender: "[you]", mine: true, text: "> a line you sent" }),
    TermLine({ kind: "a", sender: "[claude-1a2b]", text: "> a line an agent sent" }),
    TermLine({ source: "[rtt] ", text: "a line from another channel, on the All tab" }),
    TermLine({ prompt: "uart:~$ ", text: "kernel version" }),
  ] }),
};

export const CommandLine = {
  render: () => h("div", { style: "max-width:720px;padding-top:180px" }, CommandBar({
    input: h("input", { value: "kernel ", placeholder: "Type a command, Enter to send" }),
    suggest: Suggestions({ active: 1, options: [
      { name: "reboot", help: "Reboot the system" },
      { name: "stacks", help: "List threads' stack usage" },
      { name: "threads", help: "List kernel threads" },
      { name: "uptime", help: "Kernel uptime" },
      { name: "version", help: "Kernel version" },
    ] }),
  })),
};

export const CommandLineDisabled = {
  render: () => h("div", { style: "max-width:720px" }, CommandBar({ disabled: true, placeholder: "The board is offline", send: Button({ label: "Send", variant: "primary", disabled: true }) })),
};

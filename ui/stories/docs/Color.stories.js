import "./docs.css";
import { Alert, BoardCard, Button, Terminal, TermLine, h } from "../../index.js";

export default { title: "Docs/Color", parameters: { layout: "fullscreen" } };

// Values are read from app.css at render time, so this page can't drift from the dashboard.
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const STATES = [
  { id: "sim-1", token: "--sage", state: "available", status: { text: "free", tone: "free" }, line: "native_sim/native/64", lineClass: "muted mono",
    means: "Free. Any agent can take it, or you can." },
  { id: "nrf9161dk-1", token: "--pink", state: "leased", status: { text: "testing", tone: "busy" }, line: [h("b", {}, "claude: lte test"), " · 12m left"],
    means: "Held by an agent, which is flashing, testing or debugging it." },
  { id: "nrf5340dk-1", token: "--peach", state: "human", status: { text: "held by Fame", tone: "busy" }, line: [h("b", {}, "Fame")],
    means: "Paused, or taken by a person. Agents wait until it's handed back." },
  { id: "nrf52840dk-1", token: "--lilac", state: "maintenance", status: { text: "maintenance", tone: "" }, line: "nrf52840dk/nrf52840", lineClass: "muted mono",
    means: "Out of the queue on purpose. No agent will be given it." },
  { id: "nucleo-h743", token: "--err-bg", state: "offline", level: "err", status: { text: "offline", tone: "err" }, line: "Offline: probe not found", lineLevel: "err",
    means: "No pastel. A board that's offline or broken turns red, with the reason under its name." },
];

const swatch = (name, label) => h("div", { class: "doc-swatch" },
  h("span", { class: "chip-color", style: `background:var(${name})` }),
  h("code", {}, name),
  h("span", {}, label ? `${css(name)}, ${label}` : css(name)));

export const Color = {
  render: () => h("article", { class: "doc" },
    h("h1", {}, "Color tells you who has the board"),
    h("p", { class: "lede" },
      "Four pastels, each meaning one thing. A board's card in the rail and its bar over the terminal take the same tint, ",
      "so you can tell at a glance which boards are free and which an agent is using."),
    h("div", { class: "doc-states" }, STATES.map((s) => h("div", { class: "doc-state" },
      BoardCard(s),
      h("p", { class: "means" }, s.means),
      h("dl", {}, h("dt", {}, "Token"), h("dd", {}, h("code", {}, s.token)), h("dt", {}, "Value"), h("dd", {}, css(s.token)))))),

    h("h2", {}, "Yellow and red are reserved"),
    h("p", {}, "Yellow means a person needs to look: an agent asking to erase a board, a lease about to run out. ",
      "Red means something failed. Neither is used to make a thing stand out."),
    h("div", { class: "doc-pair" },
      Alert({ level: "warn", text: [h("b", {}, "codex: fota"), " asks to erase ", h("b", {}, "nrf9161dk-1")], actions: [Button({ label: "Approve", variant: "primary" }), Button({ label: "Deny" })] }),
      Alert({ level: "err", text: [h("b", {}, "nucleo-h743"), " didn't boot after flashing"], actions: [Button({ label: "Recover" })] })),
    h("div", { class: "doc-swatches" },
      swatch("--warn-bg"), swatch("--warn-fg"), swatch("--warn-line"),
      swatch("--err-bg"), swatch("--err-fg"), swatch("--err-line")),

    h("h2", {}, "Page, ink and panels"),
    h("p", {}, "A warm off-white page with a faint dot grid, near-white panels, and black ink for text and outlines. ",
      "Rose marks something that's on, such as an agent holding a board or a switch that's enabled."),
    h("div", { class: "doc-swatches" },
      swatch("--bg", "page"), swatch("--dot", "dot grid"), swatch("--card", "panels"), swatch("--ink", "text, outlines"),
      swatch("--muted", "secondary text"), swatch("--faint", "hints"), swatch("--line-strong", "dividers"), swatch("--hover", "hover, code"),
      swatch("--rose", "on")),

    h("h2", {}, "The terminal stays dark"),
    h("p", {}, "The console is the one dark surface, so log output reads like a real serial terminal. ",
      "It has its own yellow and red, bright enough to read on black."),
    h("div", { class: "doc-term" },
      Terminal({ lines: [
        TermLine({ timestamp: "[00:00:00.251,342] ", text: "<inf> lte_test: Starting LTE link tests" }),
        TermLine({ timestamp: "[00:00:04.518,903] ", text: "<wrn> lte_lc: PSM not granted by the network", kind: "w" }),
        TermLine({ kind: "a", sender: "[claude-1a2b]", text: "> at AT+CEREG?" }),
        TermLine({ kind: "h", sender: "[you]", mine: true, text: "> kernel uptime" }),
        TermLine({ timestamp: "[00:00:07.880,442] ", text: "<err> lte_test: socket connect failed: -116", kind: "e" }),
        TermLine({ kind: "d", text: "[arbiter] test run finished: 11 passed, 1 failed" }),
      ] }),
      h("div", { class: "doc-swatches" },
        swatch("--term-bg"), swatch("--term-fg"), swatch("--term-dim"), swatch("--term-warn"), swatch("--term-err")))),
};

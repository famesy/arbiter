import "./docs.css";
import { Alert, AgentRow, BoardBar, BoardCard, Button, TermCard, h } from "../../index.js";
import { boards, chips, leasedActions, leasedHolder, termLines } from "../sample.js";

export default { title: "Docs/Welcome", parameters: { layout: "fullscreen" } };

// Each legend entry outlines the parts of the live dashboard it names.
const PARTS = [
  ["Alert", ".alert", "An ask that waits for a person, such as erasing a board."],
  ["BoardCard", ".rail .board", "One board in the rail, tinted by who has it."],
  ["AgentRow", ".agent", "One agent, and the board it holds or waits for."],
  ["BoardBar", ".boardbar", "The selected board: name, status and its one main action."],
  ["HolderRow", ".holder-row", "Who holds the board and how long their lease has left."],
  ["ChipStrip", ".strip", "Queue, power, tests and activity, each opening a sheet."],
  ["Pill", ".pill", "A short status. Black means busy, an outline means free."],
  ["TermCard", ".term-card", "The live console, shared by agents and you."],
];

function anatomy() {
  const stage = h("div", { class: "doc-stage" },
    h("div", { style: "grid-column:1/-1" }, Alert({ level: "warn", text: [h("b", {}, "codex: fota"), " asks to erase ", h("b", {}, "nrf9161dk-1")],
      actions: [Button({ label: "Approve", variant: "primary" }), Button({ label: "Deny" })] })),
    h("aside", { class: "rail" },
      boards.slice(0, 3).map((b, i) => BoardCard({ ...b, selected: i === 0 })),
      h("div", { id: "sessions" },
        AgentRow({ label: "claude: lte test", dot: "on", what: "nrf9161dk-1" }),
        AgentRow({ label: "codex: fota", what: "waiting" }))),
    h("div", { style: "display:flex;flex-direction:column;gap:var(--s3);min-width:0" },
      BoardBar({ id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, actions: leasedActions(), holder: leasedHolder(), chips: chips() }),
      TermCard({ channels: [{ id: "all", label: "All" }, { id: "uart:app", label: "uart:app", note: "primary" }], lines: termLines().slice(1, 8) })));

  let pressed = null;
  const mark = (selector, on) => stage.querySelectorAll(selector).forEach((el) => el.classList.toggle("doc-hl", on));
  const legend = h("div", { class: "doc-legend" },
    h("p", {}, "Point at a name to find it in the dashboard."),
    PARTS.map(([name, selector, what]) => {
      const btn = h("button", { type: "button", "aria-pressed": "false", "data-sel": selector }, h("code", {}, name), h("span", { class: "what" }, what));
      const show = (on) => mark(selector, on || pressed === btn);
      btn.addEventListener("mouseenter", () => show(true));
      btn.addEventListener("mouseleave", () => show(false));
      btn.addEventListener("focus", () => show(true));
      btn.addEventListener("blur", () => show(false));
      btn.addEventListener("click", () => {
        if (pressed && pressed !== btn) { pressed.setAttribute("aria-pressed", "false"); mark(pressed.dataset.sel, false); }
        pressed = pressed === btn ? null : btn;
        btn.setAttribute("aria-pressed", pressed === btn ? "true" : "false");
        show(pressed === btn);
      });
      return btn;
    }));
  return h("div", { class: "doc-anatomy" }, stage, legend);
}

export const Welcome = {
  render: () => h("article", { class: "doc" },
    h("h1", {}, "Several agents, one board, and you in charge"),
    h("p", { class: "lede" },
      "These are the parts the arbiter dashboard is built from. Agents queue for a dev board, flash it and run tests; ",
      "the dashboard shows who has which board, streams its console, and lets you pause an agent or take the board yourself."),
    anatomy(),

    h("h2", {}, "Four rules the whole kit follows"),
    h("dl", { class: "doc-rules" },
      h("div", {}, h("dt", {}, "Color says who has the board"),
        h("dd", {}, "Sage is free, pink is held by an agent, peach is paused or held by you, lilac is in maintenance. Nothing else is tinted.")),
      h("div", {}, h("dt", {}, "Yellow warns, red fails"),
        h("dd", {}, "Yellow only for something that needs a person, red only for something broken. Never for decoration or emphasis.")),
      h("div", {}, h("dt", {}, "Ink outlines hold the shapes"),
        h("dd", {}, "Panels get a 2px black edge and soft corners on a dotted page. There are no shadows and no dark mode.")),
      h("div", {}, h("dt", {}, "One main action per board"),
        h("dd", {}, "The board bar has one black button for what you most likely want next. Everything else sits under Actions."))),

    h("h2", {}, "Where things live"),
    h("dl", { class: "doc-files" },
      h("dt", {}, h("code", {}, "backend/arbiter/dashboard/components/")),
      h("dd", {}, "The components. Plain ES modules that take one props object and return an element. arbiterd serves them with no build step."),
      h("dt", {}, h("code", {}, "backend/arbiter/dashboard/app.css")),
      h("dd", {}, "Every token and every style. Components only set class names, so the dashboard and these pages always match."),
      h("dt", {}, h("code", {}, "ui/stories/")),
      h("dd", {}, "One story per variant, and these docs. Run them with npm run storybook in ui/."))),
};

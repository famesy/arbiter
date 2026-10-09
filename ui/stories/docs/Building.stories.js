import "./docs.css";
import { BoardCard, Pill, h } from "../../index.js";

export default { title: "Docs/Building components", parameters: { layout: "fullscreen" } };

const USE = `import { BoardCard } from "/static/components/index.js";

const card = BoardCard({
  id: "nrf9161dk-1",
  state: "leased",
  status: { text: "testing", tone: "busy" },
  line: "claude: lte test",
  onSelect: () => openBoard("nrf9161dk-1"),
});
document.querySelector("#boards").append(card);`;

const MAKE = `import { h, cls } from "./dom.js";

/** A short status. tone: "" | "free" | "busy" | "warn" | "err". */
export function Pill({ text, tone = "", dot = true } = {}) {
  return h("span", { class: cls("pill", tone) },
    dot ? h("span", { class: "dot" }) : null, text);
}`;

export const BuildingComponents = {
  name: "Building components",
  render: () => h("article", { class: "doc" },
    h("h1", {}, "Props in, element out"),
    h("p", { class: "lede" },
      "Every component is a plain function. It takes one props object and returns a DOM element styled by app.css. ",
      "There is no framework and no build step, so the dashboard loads them straight from arbiterd."),

    h("h2", {}, "Using one"),
    h("div", { class: "doc-example" },
      h("pre", { class: "doc-code" }, USE),
      h("div", { class: "doc-result" },
        BoardCard({ id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, line: "claude: lte test", selected: true }),
        h("p", { class: "note" }, "The element it returns, rendered with the real stylesheet."))),

    h("h2", {}, "Making a new one"),
    h("div", { class: "doc-example" },
      h("pre", { class: "doc-code" }, MAKE),
      h("ol", { class: "doc-steps" },
        h("li", {}, "Put it in the file in ", h("code", {}, "components/"), " that holds its neighbours, and export it from ", h("code", {}, "index.js"), "."),
        h("li", {}, "Build it with ", h("code", {}, "h()"), " and set class names only. Colors, sizes and corners belong in ", h("code", {}, "app.css"), " as tokens."),
        h("li", {}, "Describe its props in a one-line comment above it, with the allowed values."),
        h("li", {}, "Add a story for each variant in ", h("code", {}, "ui/stories/"), ", using the sample boards in ", h("code", {}, "sample.js"), "."),
        h("li", {}, "Run ", h("code", {}, "npm test"), " in ", h("code", {}, "ui/"), ". It fails if an import points at a file the dashboard doesn't ship."))),

    h("h2", {}, "Choosing a tone"),
    h("p", {}, "Most mistakes are color mistakes. Status color follows the rules on the Color page, never taste."),
    h("div", { class: "doc-dodont" },
      h("div", {},
        h("p", { class: "verdict" }, "Do"),
        h("div", { class: "show" }, Pill({ text: "testing", tone: "busy" }), Pill({ text: "free", tone: "free" })),
        h("p", {}, "Black for busy, an outline for free. A pill only says what state the board is in.")),
      h("div", {},
        h("p", { class: "verdict no" }, "Don't"),
        h("div", { class: "show" }, Pill({ text: "testing", tone: "warn" }), Pill({ text: "free", tone: "err" })),
        h("p", {}, "Yellow for a busy board reads as a problem, and red for anything that isn't broken trains people to ignore red.")),
      h("div", {},
        h("p", { class: "verdict" }, "Do"),
        h("div", { class: "show" }, Pill({ text: "offline", tone: "err" }), Pill({ text: "lease ends in 1m", tone: "warn" })),
        h("p", {}, "Red when it's broken, yellow when someone should act soon.")))),
};

import "./docs.css";
import { h } from "../../index.js";

export default { title: "Docs/Type and spacing", parameters: { layout: "fullscreen" } };

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const serif = (size, weight, extra = "") => `font-family:var(--serif);font-size:${size}px;font-weight:${weight};letter-spacing:-0.015em;line-height:1.15;${extra}`;

// Sizes and weights as app.css sets them for each role.
const ROLES = [
  [h("div", { style: serif(34, 700) }, "nrf9161dk-1"), "Serif 34, bold", "A board's name in the board bar"],
  [h("div", { style: serif(30, 500) }, "Boards"), "Serif 30, regular", "Section titles in Settings"],
  [h("div", { style: serif(28, 700) }, "Queue"), "Serif 28, bold", "Sheet and guide titles"],
  [h("div", { style: serif(24, 600) }, "arbiter"), "Serif 24, semibold", "The brand in the header"],
  [h("div", { style: serif(19, 700) }, "sim-1"), "Serif 19, bold", "A board's name in the rail"],
  [h("div", { style: serif(17, 700) }, "3.70 V"), "Serif 17, bold", "Values in chips and the guide"],
  [h("div", {}, "Agents queue for a board, then flash it and run tests."), "Sans 14, line height 1.5", "Body text everywhere"],
  [h("div", { class: "muted", style: "font-size:13px" }, "Paused by Fame, 4m ago"), "Sans 13 or 12, muted", "Secondary facts, hints and table text"],
  [h("h2", { class: "app-label" }, "Agents"), "Sans 12, semibold, uppercase, tracked", "Rail section labels only"],
  [h("div", { class: "mono", style: "font-size:13px" }, "uart:~$ kernel uptime"), "Monospace 13", "The terminal, commands and platform names"],
];

const SPACE = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];
const RADII = [["--r-sm", "buttons, inputs"], ["--r", "terminal, menus"], ["--r-lg", "cards, sheets"]];

export const TypeAndSpacing = {
  name: "Type and spacing",
  render: () => h("article", { class: "doc" },
    h("h1", {}, "Names in serif, everything else plain"),
    h("p", { class: "lede" },
      "Board names, values and titles are set in a bookish serif so they read like labels on the bench. ",
      "Body text uses the system sans, and anything typed into or printed by a board is monospace."),
    h("div", { class: "doc-type" }, ROLES.map(([sample, spec, use]) => h("div", { class: "doc-type-row" },
      h("div", { class: "sample" }, sample),
      h("div", { class: "spec" }, h("b", {}, spec), h("span", {}, use))))),
    h("p", { class: "note", style: "margin-top:var(--s4)" },
      "The serif is Iowan Old Style where it's installed, then Palatino, Charter or Georgia. Nothing is downloaded."),

    h("h2", {}, "A 4px spacing scale"),
    h("p", {}, "Every gap and padding is one of these six steps. Use the token, not a pixel value."),
    h("div", { class: "doc-space" }, SPACE.map((n) => h("div", { class: "doc-space-row" },
      h("code", {}, n), h("span", {}, css(n)), h("div", { class: "bar", style: `width:var(${n})` })))),

    h("h2", {}, "Three corner sizes"),
    h("p", {}, "Bigger things get rounder corners. Status pills and alert buttons are fully round."),
    h("div", { class: "doc-corners" }, RADII.map(([n, use]) => h("div", { style: `border-radius:var(${n})` },
      h("span", {}, h("code", {}, n), h("br"), use))))),
};

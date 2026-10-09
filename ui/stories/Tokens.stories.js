import { h } from "../index.js";

// Foundations from app.css's :root, read at render time so the swatches never drift.
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const GROUPS = [
  ["Page and ink", ["--bg", "--dot", "--card", "--ink", "--muted", "--faint", "--line", "--line-strong", "--hover"]],
  ["Pastel panels", ["--pink", "--sage", "--peach", "--lilac", "--rose"]],
  ["Warnings (yellow) and errors (red) only", ["--warn-bg", "--warn-fg", "--warn-line", "--err-bg", "--err-fg", "--err-line"]],
  ["Terminal", ["--term-bg", "--term-fg", "--term-dim", "--term-warn", "--term-err"]],
];

function swatch(name) {
  return h("div", { style: "display:flex;flex-direction:column;gap:6px;width:132px" },
    h("div", { style: `height:64px;border-radius:var(--r);border:var(--edge) solid var(--ink);background:var(${name})` }),
    h("code", {}, name),
    h("span", { class: "muted small-text mono" }, css(name)));
}

export default {
  title: "Foundations/Tokens",
  parameters: { layout: "padded" },
};

export const Colors = {
  render: () => h("div", { style: "display:flex;flex-direction:column;gap:var(--s5)" },
    GROUPS.map(([title, names]) => h("div", { class: "card" },
      h("h2", {}, title),
      h("div", { style: "display:flex;flex-wrap:wrap;gap:var(--s4)" }, names.map(swatch))))),
};

export const Type = {
  render: () => h("div", { class: "card", style: "display:flex;flex-direction:column;gap:var(--s4)" },
    h("div", { style: "font-family:var(--serif);font-size:44px;letter-spacing:-0.02em;line-height:1.1" }, "Serif display 44"),
    h("div", { style: "font-family:var(--serif);font-size:30px;letter-spacing:-0.02em" }, "Serif heading 30"),
    h("div", { style: "font-family:var(--serif);font-size:21px;font-weight:600" }, "Serif board name 21"),
    h("h2", { style: "margin:0" }, "Small uppercase label 12"),
    h("div", {}, "Body text 14 in the system sans-serif."),
    h("div", { class: "muted" }, "Muted text for secondary facts."),
    h("code", { style: "align-self:flex-start" }, "uart:~$ kernel version")),
};

export const Spacing = {
  render: () => h("div", { class: "card", style: "display:flex;flex-direction:column;gap:var(--s3)" },
    ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"].map((n) => h("div", { style: "display:flex;align-items:center;gap:var(--s4)" },
      h("code", { style: "width:56px" }, n),
      h("div", { style: `height:16px;width:var(${n});background:var(--ink);border-radius:3px` }),
      h("span", { class: "muted small-text" }, css(n)))),
    h("h2", { style: "margin:var(--s4) 0 0" }, "Corners and edges"),
    h("div", { style: "display:flex;gap:var(--s4)" }, ["--r-sm", "--r", "--r-lg"].map((n) =>
      h("div", { style: `width:96px;height:64px;border:var(--edge) solid var(--ink);border-radius:var(${n});display:grid;place-items:center` }, h("code", {}, n))))),
};

/* The getting-started guide: a dialog with a tinted header, numbered steps, a body and
   Back / Next at the foot. It opens by itself the first time the dashboard opens. */
import { h, cls } from "./dom.js";
import { Button } from "./controls.js";

/**
 * The parts that fill dialog#guide. steps: [title]; step: the current index; tint:
 * "sage" | "peach" | "lilac" | "pink"; body: the step's content.
 */
export function GuideContent({ steps = [], step = 0, kicker, title, tint = "sage", body = [], onStep, onSkip, onBack, onNext } = {}) {
  const last = step === steps.length - 1;
  return [
    h("div", { class: `guide-head ${tint}` },
      h("div", { class: "guide-steps" }, steps.map((t, i) => h("button", {
        type: "button",
        class: cls("step", i === step ? "on" : i < step ? "done" : ""),
        "aria-label": t,
        onclick: onStep ? () => onStep(i) : null,
      }, String(i + 1)))),
      h("div", { class: "k" }, kicker || (step === 0 ? "Welcome to arbiter" : `Step ${step + 1} of ${steps.length}`)),
      h("h2", { id: "guide-title" }, title || steps[step] || "")),
    h("div", { class: "guide-body" }, body),
    h("div", { class: "guide-foot" },
      Button({ label: last ? "Close" : "Skip the guide", variant: "link", onclick: onSkip }),
      h("span", { class: "spacer" }),
      step ? Button({ label: "Back", onclick: onBack }) : null,
      Button({ label: last ? "Done" : "Next", variant: "primary", onclick: onNext })),
  ];
}

/** The guide dialog with its content. open shows it in place (for stories); the dashboard calls showModal(). */
export function Guide({ open = false, ...props } = {}) {
  return h("dialog", { id: "guide", open: open || null, "aria-labelledby": "guide-title" }, GuideContent(props));
}

/** A framed row in a guide list: a board or a probe, with a pill or button on the right. */
export function GuideRow({ name, detail, mono = false, end } = {}) {
  return h("div", { class: "row" }, h("b", { class: cls("name", mono && "mono") }, name), detail ? h("span", { class: "mono muted" }, detail) : null, end || null);
}

/** A list of GuideRows. */
export function GuideList({ rows = [] } = {}) {
  return h("div", { class: "guide-list" }, rows.map((r) => (r instanceof Node ? r : GuideRow(r))));
}

/** Health check counts as pills: OK, warnings, failed. */
export function Tally({ ok = 0, warn = 0, fail = 0 } = {}) {
  return h("div", { class: "tally" },
    h("span", { class: "t ok" }, h("b", {}, String(ok)), " OK"),
    h("span", { class: cls("t", warn && "warn") }, h("b", {}, String(warn)), " warnings"),
    h("span", { class: cls("t", fail && "err") }, h("b", {}, String(fail)), " failed"));
}

/** A dark box with a command to paste, and a Copy button. */
export function CmdBox({ text } = {}) {
  const copy = Button({ label: "Copy", size: "small", onclick: (ev) => {
    const btn = ev.currentTarget;
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(text).then(() => { btn.textContent = "Copied"; setTimeout(() => { btn.textContent = "Copy"; }, 1500); }, () => {});
  } });
  return h("div", { class: "cmd-box" }, h("pre", {}, text), copy);
}

/** A numbered tip: a pink circled number, a bold title and a line under it. */
export function TourItem({ n, title, text } = {}) {
  return h("div", { class: "tour-item" }, h("span", { class: "n" }, String(n)), h("div", {}, h("b", {}, title), h("div", { class: "muted" }, text)));
}

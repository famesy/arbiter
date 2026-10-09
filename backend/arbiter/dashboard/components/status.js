/* Status labels and messages. Yellow (warn) and red (err) only ever mean "look at this". */
import { h, cls } from "./dom.js";

/** A rounded status label. tone: "" | "free" (outlined) | "busy" (ink) | "warn" | "err". */
export function Pill({ text, tone = "", dot = true } = {}) {
  return h("span", { class: cls("pill", tone) }, dot ? h("span", { class: "dot" }) : null, text);
}

/** The header's connection pill: "Live", or red "Reconnecting to arbiterd". */
export function ConnPill({ up = true } = {}) {
  return h("span", { id: "conn", class: cls("pill", !up && "down") },
    h("span", { class: "dot" }), h("span", { id: "conn-text" }, up ? "Live" : "Reconnecting to arbiterd"));
}

/** A small outlined tag, like "applies now" or "after restart" on a settings field. */
export function Tag({ text, restart = false } = {}) {
  return h("span", { class: cls("tag", restart && "restart") }, text);
}

/**
 * A banner across the top of the page, used for approvals an agent is waiting on.
 * level: "warn" | "err" | "note". text may hold elements. actions: buttons on the right.
 */
export function Alert({ text, level = "warn", actions = [] } = {}) {
  return h("div", { class: `alert ${level}`, role: level === "note" ? null : "status" },
    h("span", { class: "text" }, text),
    actions.length ? h("span", { class: "btn-row" }, actions) : null);
}

/** One problem with a board, shown under its name. level: "warn" | "err". */
export function Issue({ text, level = "warn" } = {}) {
  return h("div", { class: `issue ${level}` }, text);
}

/** A short message in the corner. level: "" | "warn" | "err". */
export function Toast({ text, level = "" } = {}) {
  return h("div", { class: cls("toast", level), role: "status" }, text);
}

/** Grey placeholder text for an empty list. */
export function Empty({ text, children = [] } = {}) {
  return h("div", { class: "empty" }, text, children);
}

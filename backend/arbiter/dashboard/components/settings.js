/* The Settings page: sections with serif titles, read-only fields, health-check rows and
   switches for this browser's preferences. */
import { h, cls } from "./dom.js";

/** A settings section card with a serif title and a sentence under it. */
export function Section({ id, title, sub, children = [] } = {}) {
  return h("section", { class: "card set-section", id: id ? `set-${id}` : null },
    h("h2", {}, title), sub ? h("p", { class: "sub" }, sub) : null, children);
}

/** A read-only setting: label, value and an optional hint. muted greys out a missing value. */
export function Field({ label, value, hint, muted = false } = {}) {
  return h("div", { class: "field" },
    h("div", { class: "label" }, label),
    h("div", { class: cls("value", muted && "muted") }, value),
    hint ? h("div", { class: "hint" }, hint) : null);
}

/** A titled group of fields. */
export function FieldGroup({ title, children = [] } = {}) {
  return h("div", { class: "set-group" }, h("h3", {}, title), h("div", { class: "fields" }, children));
}

/** One health-check result. status: "OK" | "WARN" | "FAIL". */
export function CheckRow({ status = "OK", name, detail = "" } = {}) {
  return h("div", { class: cls("check-row", status === "FAIL" ? "err" : status === "WARN" ? "warn" : "") },
    h("span", { class: "st" }, status === "OK" ? "OK" : status === "WARN" ? "Warn" : "Fail"),
    h("span", { class: "n" }, name),
    h("span", { class: "d" }, detail));
}

/** A card per board in Settings, with its name in serif and pills beside it. */
export function BoardSettings({ id, pills = [], actions, editing = false, children = [] } = {}) {
  return h("div", { class: cls("board-set", editing && "editing") },
    h("div", { class: "board-set-head" }, h("h3", {}, id), pills, h("span", { class: "spacer" }), actions || null),
    children);
}

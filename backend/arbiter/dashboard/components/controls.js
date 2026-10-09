/* Buttons, menus, tabs and switches. Everything clickable is a pill with an ink outline. */
import { h, cls } from "./dom.js";

/**
 * A pill button. variant: "" | "primary" (ink fill, the one main action) | "danger" |
 * "link" (underlined text). size: "" | "small" | "icon". Other attributes (title,
 * disabled, aria-label, onclick, type, ...) pass through.
 */
export function Button({ label, variant = "", size = "", class: extra, ...attrs } = {}) {
  return h("button", { type: "button", ...attrs, class: cls(variant, size, extra) || null }, label);
}

/** A row of buttons. The string "sep" in items draws a thin divider. */
export function ButtonRow({ items = [], class: extra } = {}) {
  return h("div", { class: cls("btn-row", extra) }, items.map((x) => (x === "sep" ? h("span", { class: "sep" }) : x)));
}

/**
 * A pill that opens a small panel below it: the board's Actions ▾ menu, the header's ⋯
 * menu and the terminal's View menu. items are elements (buttons, labels) for the panel.
 */
export function Menu({ label, items = [], open = false, id, ariaLabel } = {}) {
  const menu = h("details", { class: "menu", id: id || null, open: open || null },
    h("summary", { "aria-label": ariaLabel || null, title: ariaLabel || null }, label),
    h("div", { class: "menu-body" }, items));
  // Picking an item closes the menu.
  for (const b of menu.querySelectorAll(".menu-body button")) b.addEventListener("click", () => setTimeout(() => { menu.open = false; }, 0));
  return menu;
}

/** A menu of checkboxes, like the terminal's View options. options: [{ id, label, checked }]. */
export function CheckMenu({ label = "View", options = [], open = false, onChange } = {}) {
  return Menu({
    label,
    open,
    items: options.map((o) => h("label", {},
      h("input", { type: "checkbox", "data-view": o.id, checked: !!o.checked, onchange: onChange ? (ev) => onChange(o.id, ev.target.checked) : null }),
      o.label)),
  });
}

/**
 * Segmented pill tabs, like the terminal's channel picker. items: [{ id, label, note?,
 * title? }]; note shows dimmed after the label ("All", "uart:app · primary").
 */
export function Tabs({ items = [], active, onSelect } = {}) {
  return h("div", { class: "tabs", role: "tablist" }, items.map((t) => h("button", {
    type: "button",
    role: "tab",
    class: t.id === active ? "on" : "",
    "aria-selected": t.id === active ? "true" : "false",
    title: t.title || null,
    onclick: onSelect ? () => onSelect(t.id) : null,
  }, t.label, t.note ? h("span", { class: "muted" }, ` · ${t.note}`) : null)));
}

/** The page switcher in the header. items: [{ id, label, href }]. */
export function NavTabs({ items = [], active, id = "nav" } = {}) {
  return h("nav", { class: "tabs", id }, items.map((t) =>
    h("a", { href: t.href || "#", "data-page": t.id, class: t.id === active ? "on" : null }, t.label)));
}

/** An on/off switch (a styled checkbox). */
export function Switch({ checked = false, label, onChange } = {}) {
  return h("input", {
    type: "checkbox",
    class: "switch",
    checked: !!checked,
    "aria-label": label || null,
    onchange: onChange ? (ev) => onChange(ev.target.checked) : null,
  });
}

/** A settings row: label and hint on the left, a switch on the right. */
export function ToggleRow({ label, hint, checked = false, onChange } = {}) {
  return h("label", { class: "toggle-row" },
    h("span", {}, h("span", { class: "label" }, label), hint ? h("span", { class: "hint" }, hint) : null),
    Switch({ checked, onChange }));
}

/** A small checkbox with its label, like "Selected board only" over the activity feed. */
export function Check({ label, checked = false, id, onChange } = {}) {
  return h("label", { class: "check" },
    h("input", { type: "checkbox", id: id || null, checked: !!checked, onchange: onChange ? (ev) => onChange(ev.target.checked) : null }), ` ${label}`);
}

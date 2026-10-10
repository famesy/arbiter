/* Boards and agents: the rail on the left, and the bar over the selected board's terminal.
   Boards are tinted by state: sage free, pink in use, peach held or paused, lilac in
   maintenance. Problems turn them yellow or red. */
import { h, cls } from "./dom.js";
import { Pill, Issue } from "./status.js";
import { Button } from "./controls.js";

/** Board states, lower case, as the CSS tints them. */
export const BOARD_STATES = ["available", "leased", "paused", "human", "maintenance", "offline", "needs_recover"];

/**
 * One board in the rail: name, status pill and one line under it.
 * state: one of BOARD_STATES. status: { text, tone } for the pill. level: "" | "warn" |
 * "err" when something needs attention. line: text or elements; lineLevel colours it.
 */
export function BoardCard({ id, state = "available", status, level = "", selected = false, line, lineLevel = "", lineClass = "", onSelect } = {}) {
  return h("div", {
    class: cls("board", `st-${state}`, selected && "sel", level),
    tabindex: "0",
    role: "button",
    "aria-pressed": selected ? "true" : "false",
    onclick: onSelect || null,
    onkeydown: onSelect ? (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(ev); } } : null,
  },
    h("div", { class: "top" }, h("span", { class: "name" }, id), Pill(status || { text: state, tone: state === "available" ? "free" : "busy" })),
    line ? h("div", { class: cls("line", lineLevel, lineClass) }, line) : null);
}

/** A dashed button under the boards when a probe is plugged in but not set up. */
export function ProbeChip({ count = 1, onClick } = {}) {
  return h("button", { type: "button", class: "probe-chip", onclick: onClick || null },
    h("b", {}, `${count} new probe${count === 1 ? "" : "s"}`), " found · Add");
}

/**
 * One agent in the rail. dot: "" (idle) | "on" (holds a board) | "warn" (not responding).
 * what: what it is doing, on the right ("nrf9161dk-1", "waiting for sim-1", "idle").
 */
export function AgentRow({ label, dot = "", what, title } = {}) {
  return h("div", { class: "agent", title: title || null },
    h("span", { class: cls("dot", dot) }), h("b", { class: "who" }, label), h("span", { class: "what" }, what || ""));
}

/**
 * Who has the board, framed, with the time left set large. Leave holder out for a free
 * board, which shows its platform instead.
 */
export function HolderRow({ holder, paused = false, left, op, reason, platform } = {}) {
  if (!holder) return h("div", { class: "holder-row" }, h("span", { class: "muted mono" }, platform || ""));
  return h("div", { class: "holder-row" },
    h("span", { class: "holder" }, h("span", { class: "k" }, paused ? "Paused" : "Held by"), h("b", {}, holder)),
    left ? h("span", { class: "left" }, h("span", { class: "big-num" }, left), left === "on hold" || left.startsWith("ends") ? "" : " left") : null,
    op ? h("span", { class: "op" }, op) : null,
    reason ? h("span", { class: "reason", title: reason }, `“${reason}”`) : null);
}

/** A chip under the board's name that opens a panel. tone: "" | "on" | "ok" | "warn" | "err". */
export function Chip({ label, value, tone = "", onClick } = {}) {
  return h("button", { type: "button", class: cls("chip", tone), onclick: onClick || null },
    h("span", { class: "k" }, label), value ? h("b", {}, value) : null);
}

/** The row of chips: Queue, Power, Tests, Activity. chips: Chip props. */
export function ChipStrip({ chips = [] } = {}) {
  return h("div", { class: "strip" }, chips.map(Chip));
}

/** The board's actions: its one main button, the rest under Actions ▾, and Info. */
export function BoardActions({ main, more = [], onInfo } = {}) {
  const menu = more.length ? h("details", { class: "menu" }, h("summary", {}, "Actions ▾"), h("div", { class: "menu-body" }, more)) : null;
  if (menu) for (const x of more) x.addEventListener("click", () => setTimeout(() => { menu.open = false; }, 0));
  return h("div", { class: "head-actions" }, main || null, menu, Button({ label: "Info", onclick: onInfo }));
}

/**
 * The bar over the terminal: the board's name in large serif, its status, its actions,
 * who holds it, the chips, and any problems. Tinted like the board's rail card.
 * actions: a BoardActions element. holder: a HolderRow element. issues: [{ text, level }].
 */
export function BoardBar({ id, state = "available", level = "", status, actions, holder, chips = [], issues = [] } = {}) {
  return h("div", { class: cls("boardbar", `st-${state}`, level) },
    h("div", { class: "head-row" },
      h("div", { class: "head-main" }, h("span", { class: "name" }, id), status ? Pill(status) : null),
      actions || null),
    h("div", { class: "meta-row" }, holder || null, ChipStrip({ chips })),
    h("div", { class: "issues" }, issues.map(Issue)));
}

/** Label/value pairs in two columns, as in the board's Info sheet. rows: [[label, value, tone?]]; falsy rows are skipped. */
export function KeyValues({ rows = [] } = {}) {
  return h("div", { class: "kv" }, rows.filter(Boolean).map(([k, v, tone]) =>
    [h("span", { class: "k" }, k), h("span", { class: cls("v", tone) }, v)]));
}

/* What the chips open: the queue, power, test runs and activity, each in a sheet. */
import { h, cls } from "./dom.js";
import { Button } from "./controls.js";
import { Pill } from "./status.js";

/**
 * A sheet: the dialog the chips and Info open over the page, with a serif title and a
 * close button. open shows it in place (for stories); the dashboard calls showModal().
 */
export function Sheet({ title, children = [], open = false, id = "sheet", onClose } = {}) {
  return h("dialog", { id: id || null, open: open || null, "aria-labelledby": id ? `${id}-title` : null },
    h("div", { class: "sheet-head" }, h("h2", { id: id ? `${id}-title` : null }, title),
      Button({ label: "×", size: "icon", "aria-label": "Close", onclick: onClose || ((ev) => ev.currentTarget.closest("dialog").close()) })),
    h("div", { id: id ? `${id}-body` : null, class: "sheet-body" }, children));
}

/**
 * One agent waiting for a board. priority: "low" | "normal" | "high" | "urgent"; urgent
 * rows show a dark pill. Leave a callback out to disable its button.
 */
export function QueueRow({ position, who, reason, priority = "normal", front = false, urgent = false, waiting, onUp, onDown, onUrgent, onRemove } = {}) {
  return h("tr", {},
    h("td", { class: "num muted" }, position),
    h("td", {}, h("div", {}, who), reason ? h("div", { class: "sub" }, reason) : null),
    h("td", {}, h("span", { class: cls("pill", urgent && "busy") }, String(priority), front && !urgent ? " · front" : "")),
    h("td", { class: "num" }, waiting),
    h("td", { class: "actions" }, h("span", { class: "btn-row" },
      Button({ label: "↑", size: "icon", disabled: !onUp, title: "Move up", "aria-label": "Move up", onclick: onUp }),
      Button({ label: "↓", size: "icon", disabled: !onDown, title: "Move down", "aria-label": "Move down", onclick: onDown }),
      Button({ label: "Urgent", size: "small", disabled: urgent || !onUrgent, title: "Mark urgent and move to the front", onclick: onUrgent }),
      Button({ label: "Remove", size: "small", variant: "danger", title: "Remove from the queue", onclick: onRemove }))));
}

/** A board's queue. rows: QueueRow props, in order. */
export function QueueTable({ rows = [], empty = "Nobody is waiting for this board." } = {}) {
  if (!rows.length) return h("div", { class: "empty" }, empty);
  return h("table", {},
    h("tr", {}, h("th", {}, "#"), h("th", {}, "Agent"), h("th", {}, "Priority"), h("th", {}, "Waiting"), h("th", {})),
    rows.map((r, i) => QueueRow({ position: i + 1, ...r })));
}

/** One measurement: a small label over a big number. */
export function Stat({ label, value } = {}) {
  return h("div", { class: "stat" }, h("div", { class: "k" }, label), h("div", { class: "big" }, value));
}

/** A sage strip of measurements (average, peak, ...). warn turns it yellow. stats: [[label, value]]. */
export function StatStrip({ stats = [], warn = false, note } = {}) {
  return h("div", { class: cls("stats", warn && "warn") },
    stats.map(([label, value]) => Stat({ label, value })),
    note ? h("div", { style: "flex-basis:100%" }, note) : null);
}

/** A small line chart of recent measurements: solid average, dashed peak. points: [{ avg, peak }]. */
export function Sparkline({ points = [], caption } = {}) {
  const W = 420, H = 64, pad = 3;
  const max = Math.max(...points.map((x) => x.peak || x.avg || 0)) || 1;
  const xs = (i) => pad + (i * (W - 2 * pad)) / Math.max(1, points.length - 1);
  const ys = (v) => H - pad - (v / max) * (H - 2 * pad);
  const pts = (k) => points.map((x, i) => `${xs(i).toFixed(1)},${ys(x[k] || 0).toFixed(1)}`).join(" ");
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  for (const [k, dash, op] of [["peak", "4 4", "0.45"], ["avg", "", "1"]]) {
    const pl = document.createElementNS(ns, "polyline");
    pl.setAttribute("points", pts(k));
    pl.setAttribute("fill", "none");
    pl.setAttribute("stroke", "currentColor");
    pl.setAttribute("stroke-width", "2");
    pl.setAttribute("stroke-linejoin", "round");
    pl.setAttribute("vector-effect", "non-scaling-stroke");
    pl.setAttribute("opacity", op);
    if (dash) pl.setAttribute("stroke-dasharray", dash);
    svg.append(pl);
  }
  return h("div", { class: "spark" }, caption ? h("div", { class: "hint", style: "margin:0 0 var(--s2)" }, caption) : null, svg);
}

/**
 * The power sheet. state: { on, fault, volts } as shown at the top; range: "safe range
 * 3.0–4.2 V". controls: buttons for on/off/cycle/voltage (leave out when there's no
 * switch). locked: an agent holds the board. stats, history: StatStrip props and
 * Sparkline points.
 */
export function PowerPanel({ on = true, fault, volts, range, controls, locked = false, stats, history, empty } = {}) {
  return h("div", { class: "power-panel" },
    h("div", { class: "power-top" },
      Pill({ tone: fault ? "err" : on ? "busy" : "warn", text: fault ? `Fault: ${fault}` : on ? "On" : "Off" }),
      volts ? h("span", { class: "big" }, volts) : null,
      range ? h("span", { class: "muted small-text" }, range) : null),
    controls ? h("div", { class: "power-row btn-row" }, controls) : null,
    locked ? h("div", { class: "hint" }, "An agent holds this board. Pause it or take over to change power.") : null,
    stats ? StatStrip(stats) : empty ? h("div", { class: "hint" }, empty) : null,
    history && history.points && history.points.length > 1 ? Sparkline(history) : null);
}

/** One test run. result: { text, tone } for its pill. tail: the last log lines. */
export function TestRunRow({ started, agent, result, failed = false, time, logPath, junit, tail } = {}) {
  return h("tr", { class: failed ? "err" : null },
    h("td", { class: "num muted" }, started),
    h("td", {}, agent),
    h("td", { class: "result" },
      Pill(result),
      (tail && tail.length) || logPath ? h("details", { style: "margin-top:var(--s1)" }, h("summary", {}, "Log"),
        h("div", { class: "mono sub" }, logPath || ""),
        junit ? h("div", { class: "mono sub" }, `junit: ${junit}`) : null,
        tail ? h("pre", { class: "tail" }, tail.join("\n")) : null) : null),
    h("td", { class: "num" }, time));
}

/** A board's test runs, newest first. rows: TestRunRow props. */
export function TestRunsTable({ rows = [], empty = "No test runs on this board yet." } = {}) {
  if (!rows.length) return h("div", { class: "empty" }, empty);
  return h("table", {},
    h("tr", {}, h("th", {}, "Started"), h("th", {}, "Agent"), h("th", {}, "Result"), h("th", {}, "Time")),
    rows.map(TestRunRow));
}

/** One line of the activity feed. level: "" | "warn" | "err". */
export function EventRow({ time, text, level = "" } = {}) {
  return h("div", { class: cls("ev", level) }, h("span", { class: "t" }, time), h("span", {}, text));
}

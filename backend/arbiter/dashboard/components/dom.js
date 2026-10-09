/* DOM helpers every component builds on. Plain ES module: the dashboard imports it
   from /static/components/ with no build step, and ui/ shows the components in Storybook. */

/** Make an element. attrs: on* keys add listeners, class sets className, true sets a bare attribute. */
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

/** Replace an element's children, skipping null, undefined and false. */
export function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
}

/** Join class names, skipping empty ones. */
export const cls = (...names) => names.filter(Boolean).join(" ");

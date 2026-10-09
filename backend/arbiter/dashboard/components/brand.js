/* The arbiter mark and wordmark. */
import { h } from "./dom.js";

const LOGO = '<rect x="22" y="22" width="20" height="20" rx="4.5"/><circle cx="32" cy="11.5" r="6"/>' +
  '<circle cx="52.78" cy="20.00" r="4.8"/><circle cx="52.78" cy="44.00" r="4.0"/><circle cx="32.00" cy="56.00" r="3.3"/>' +
  '<circle cx="11.22" cy="44.00" r="2.7"/><circle cx="11.22" cy="20.00" r="2.2"/>';

/** The mark: a board with agents of falling size waiting their turn around it. */
export function Logo() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "logo");
  svg.setAttribute("viewBox", "0 0 64 64");
  svg.setAttribute("fill", "currentColor");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = LOGO;
  return svg;
}

/** Mark and wordmark, as in the header. as: "span" in the header, "h1" on the login card. */
export function Brand({ as = "span" } = {}) {
  return h(as, { class: "brand" }, Logo(), "arbiter");
}

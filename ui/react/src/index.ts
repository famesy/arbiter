/* React versions of the arbiter dashboard components. Each renders the same markup and
   class names as its plain twin in backend/arbiter/dashboard/components/, so it is styled
   by the dashboard's own app.css (shipped here as style.css). test/parity.test.mjs checks
   the two render the same HTML. */
export * from "./brand.js";
export * from "./controls.js";
export * from "./status.js";
export * from "./board.js";
export * from "./terminal.js";
export * from "./panels.js";
export * from "./guide.js";
export * from "./settings.js";

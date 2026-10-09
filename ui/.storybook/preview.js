import "../style.css";

/** @type { import('@storybook/html-vite').Preview } */
export default {
  parameters: {
    layout: "padded",
    // The dashboard is light pastel only; the dotted page background comes from app.css.
    backgrounds: { disable: true },
    controls: { expanded: true },
    options: {
      storySort: { order: ["Docs", ["Welcome", "Color", "Type and spacing", "Building components"], "Foundations", "Components", "Pages"] },
    },
  },
};

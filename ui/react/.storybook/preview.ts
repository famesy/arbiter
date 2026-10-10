import type { Preview } from "@storybook/react-vite";
import "../../../backend/arbiter/dashboard/app.css";

const preview: Preview = {
  parameters: {
    layout: "padded",
    // The dashboard is light pastel only; the dotted page background comes from app.css.
    backgrounds: { disable: true },
    controls: { expanded: true },
  },
};
export default preview;

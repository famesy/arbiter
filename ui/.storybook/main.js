import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../..", import.meta.url));

/** @type { import('@storybook/html-vite').StorybookConfig } */
export default {
  framework: { name: "@storybook/html-vite", options: {} },
  stories: ["../stories/**/*.stories.js"],
  core: { disableTelemetry: true },
  // The components and app.css sit in backend/arbiter/dashboard, outside this package.
  viteFinal: (config) => ({ ...config, server: { ...config.server, fs: { ...(config.server && config.server.fs), allow: [repo] } } }),
};

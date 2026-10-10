import { fileURLToPath } from "node:url";
import type { StorybookConfig } from "@storybook/react-vite";

const repo = fileURLToPath(new URL("../../..", import.meta.url));

const config: StorybookConfig = {
  framework: { name: "@storybook/react-vite", options: {} },
  stories: ["../stories/**/*.stories.tsx"],
  core: { disableTelemetry: true },
  // app.css sits in backend/arbiter/dashboard, outside this package.
  viteFinal: (config) => ({ ...config, server: { ...config.server, fs: { ...config.server?.fs, allow: [repo] } } }),
};
export default config;

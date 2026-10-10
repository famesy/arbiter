import type { Meta, StoryObj } from "@storybook/react-vite";
import { Suggestions } from "../src/index.js";

const meta = {
  title: "Terminal/Suggestions",
  component: Suggestions,
  decorators: [(S) => <div style={{ maxWidth: 720, paddingTop: 180 }}><form className="term-input"><S /><input defaultValue="kernel " /></form></div>],
} satisfies Meta<typeof Suggestions>;
export default meta;
type Story = StoryObj<typeof meta>;

export const KernelCommands: Story = {
  args: { active: 1, options: [
    { name: "reboot", help: "Reboot the system" },
    { name: "stacks", help: "List threads' stack usage" },
    { name: "threads", help: "List kernel threads" },
    { name: "uptime", help: "Kernel uptime" },
    { name: "version", help: "Kernel version" },
  ] },
};

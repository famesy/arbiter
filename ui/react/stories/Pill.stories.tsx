import type { Meta, StoryObj } from "@storybook/react-vite";
import { Pill } from "../src/index.js";

const meta = {
  title: "Status/Pill",
  component: Pill,
  args: { text: "testing", tone: "busy", dot: true },
  argTypes: { tone: { control: "inline-radio", options: ["", "free", "busy", "warn", "err"] } },
} satisfies Meta<typeof Pill>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Busy: Story = {};
export const Free: Story = { args: { text: "free", tone: "free" } };
export const Plain: Story = { args: { text: "maintenance", tone: "" } };
export const Warn: Story = { args: { text: "agent not responding", tone: "warn" } };
export const Err: Story = { args: { text: "offline", tone: "err" } };
export const NoDot: Story = { args: { text: "available", tone: "free", dot: false } };

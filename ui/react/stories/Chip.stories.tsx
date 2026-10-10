import type { Meta, StoryObj } from "@storybook/react-vite";
import { Chip } from "../src/index.js";

const meta = {
  title: "Board/Chip",
  component: Chip,
  argTypes: { tone: { control: "inline-radio", options: ["", "on", "ok", "warn", "err"] } },
  decorators: [(S) => <div className="strip"><S /></div>],
} satisfies Meta<typeof Chip>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Queue: Story = { args: { label: "Queue", value: "1", tone: "on" } };
export const Power: Story = { args: { label: "Power", value: "3.70 V" } };
export const TestsPassed: Story = { args: { label: "Tests", value: "passed", tone: "ok" } };
export const PowerOff: Story = { args: { label: "Power", value: "off", tone: "warn" } };
export const TestsFailed: Story = { args: { label: "Tests", value: "failed", tone: "err" } };
export const LabelOnly: Story = { args: { label: "Activity" } };

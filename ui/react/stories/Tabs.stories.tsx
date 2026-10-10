import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tabs } from "../src/index.js";
import { channels } from "./sample.js";

const meta = {
  title: "Controls/Tabs",
  component: Tabs,
  args: { items: channels, active: "all" },
  argTypes: { active: { control: "inline-radio", options: ["all", "uart:app", "rtt"] } },
} satisfies Meta<typeof Tabs>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Channels: Story = {};
export const SecondSelected: Story = { args: { active: "uart:app" } };

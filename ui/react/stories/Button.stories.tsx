import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button } from "../src/index.js";

const meta = {
  title: "Controls/Button",
  component: Button,
  args: { label: "Take board", variant: "primary", size: "", disabled: false },
  argTypes: {
    variant: { control: "inline-radio", options: ["", "primary", "danger", "link"] },
    size: { control: "inline-radio", options: ["", "small", "icon"] },
  },
} satisfies Meta<typeof Button>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Primary: Story = {};
export const Plain: Story = { args: { label: "Take over", variant: "" } };
export const Danger: Story = { args: { label: "Revoke lease", variant: "danger" } };
export const Small: Story = { args: { label: "Run again", variant: "", size: "small" } };
export const Icon: Story = { args: { label: "×", variant: "", size: "icon", "aria-label": "Close" } };
export const Disabled: Story = { args: { label: "Reset", variant: "", disabled: true, title: "Pause the agent or take over first" } };
export const Link: Story = { args: { label: "Skip the guide", variant: "link" } };

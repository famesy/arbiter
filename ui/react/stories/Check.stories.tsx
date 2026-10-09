import type { Meta, StoryObj } from "@storybook/react-vite";
import { Check } from "../src/index.js";

const meta = { title: "Controls/Check", component: Check } satisfies Meta<typeof Check>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Unchecked: Story = { args: { label: "Selected board only" } };
export const Checked: Story = { args: { label: "Selected board only", checked: true } };

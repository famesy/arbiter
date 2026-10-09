import type { Meta, StoryObj } from "@storybook/react-vite";
import { Switch } from "../src/index.js";

const meta = { title: "Controls/Switch", component: Switch } satisfies Meta<typeof Switch>;
export default meta;
type Story = StoryObj<typeof meta>;

export const On: Story = { args: { checked: true, label: "On" } };
export const Off: Story = { args: { checked: false, label: "Off" } };

import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button, Menu } from "../src/index.js";

const meta = { title: "Controls/Menu", component: Menu, decorators: [(S) => <div style={{ height: 220 }}><S /></div>] } satisfies Meta<typeof Menu>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ActionsOpen: Story = {
  args: { label: "Actions ▾", open: true, items: [<Button key="t" label="Take over" />, <Button key="x" label="+15 min" />, <Button key="s" label="Reset" disabled />, <Button key="r" label="Revoke lease" variant="danger" />] },
};

export const Closed: Story = { args: { label: "⋯", ariaLabel: "More", items: [<Button key="p" label="Pause all agents" />] } };

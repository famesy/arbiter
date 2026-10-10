import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button, ButtonRow } from "../src/index.js";

const meta = { title: "Controls/ButtonRow", component: ButtonRow } satisfies Meta<typeof ButtonRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const BoardActions: Story = {
  args: { items: [<Button key="p" label="Pause agent" variant="primary" />, <Button key="t" label="Take over" />, <Button key="x" label="+15 min" />, "sep", <Button key="r" label="Revoke lease" variant="danger" />] },
};

export const SmallButtons: Story = {
  args: { items: [<Button key="a" label="Run again" size="small" />, <Button key="u" label="Urgent" size="small" />, <Button key="r" label="Remove" size="small" variant="danger" />,
    <Button key="up" label="↑" size="icon" aria-label="Move up" />, <Button key="c" label="×" size="icon" aria-label="Close" />] },
};

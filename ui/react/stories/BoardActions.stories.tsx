import type { Meta, StoryObj } from "@storybook/react-vite";
import { BoardActions, Button } from "../src/index.js";

const meta = { title: "Board/BoardActions", component: BoardActions, decorators: [(S) => <div style={{ height: 220 }}><S /></div>] } satisfies Meta<typeof BoardActions>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Leased: Story = {
  args: { main: <Button label="Pause agent" variant="primary" />, more: [<Button key="t" label="Take over" />, <Button key="x" label="+15 min" />, <Button key="r" label="Revoke lease" variant="danger" />] },
};
export const Free: Story = { args: { main: <Button label="Take board" variant="primary" />, more: [<Button key="r" label="Reset" />, <Button key="m" label="Maintenance" />] } };

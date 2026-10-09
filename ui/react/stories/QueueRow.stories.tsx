import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueueRow } from "../src/index.js";
import { queue } from "./sample.js";

const meta = { title: "Panels/QueueRow", component: QueueRow, decorators: [(S) => <div className="card" style={{ maxWidth: 760 }}><table><tbody><S /></tbody></table></div>] } satisfies Meta<typeof QueueRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Normal: Story = { args: { position: 1, ...queue[0] } };
export const FrontOfQueue: Story = { args: { position: 2, ...queue[1] } };
export const Urgent: Story = { args: { position: 3, ...queue[2] } };

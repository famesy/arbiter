import type { Meta, StoryObj } from "@storybook/react-vite";
import { QueueTable } from "../src/index.js";
import { queue } from "./sample.js";

const meta = { title: "Panels/QueueTable", component: QueueTable, decorators: [(S) => <div className="card scroll-x" style={{ maxWidth: 760 }}><S /></div>] } satisfies Meta<typeof QueueTable>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ThreeWaiting: Story = { args: { rows: queue } };
export const Nobody: Story = { args: { rows: [] } };

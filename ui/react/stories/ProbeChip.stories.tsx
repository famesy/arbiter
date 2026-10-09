import type { Meta, StoryObj } from "@storybook/react-vite";
import { ProbeChip } from "../src/index.js";

const meta = { title: "Board/ProbeChip", component: ProbeChip, decorators: [(S) => <aside className="rail" style={{ position: "static", width: 250 }}><S /></aside>] } satisfies Meta<typeof ProbeChip>;
export default meta;
type Story = StoryObj<typeof meta>;

export const OneProbe: Story = { args: { count: 1 } };
export const TwoProbes: Story = { args: { count: 2 } };

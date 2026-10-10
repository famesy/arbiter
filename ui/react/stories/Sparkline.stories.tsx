import type { Meta, StoryObj } from "@storybook/react-vite";
import { Sparkline } from "../src/index.js";
import { history } from "./sample.js";

const meta = { title: "Panels/Sparkline", component: Sparkline, decorators: [(S) => <div className="card" style={{ maxWidth: 760 }}><S /></div>] } satisfies Meta<typeof Sparkline>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Current: Story = { args: { points: history, caption: "Last 24 measurements · solid average, dashed peak · top 3.30 mA" } };

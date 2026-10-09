import type { Meta, StoryObj } from "@storybook/react-vite";
import { Stat } from "../src/index.js";

const meta = { title: "Panels/Stat", component: Stat, decorators: [(S) => <div className="stats"><S /></div>] } satisfies Meta<typeof Stat>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Average: Story = { args: { label: "Average", value: "1.12 mA" } };

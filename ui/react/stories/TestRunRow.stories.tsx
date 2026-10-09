import type { Meta, StoryObj } from "@storybook/react-vite";
import { TestRunRow } from "../src/index.js";
import { runs } from "./sample.js";

const meta = { title: "Panels/TestRunRow", component: TestRunRow, decorators: [(S) => <div className="card" style={{ maxWidth: 760 }}><table><tbody><S /></tbody></table></div>] } satisfies Meta<typeof TestRunRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Running: Story = { args: runs[0] };
export const Failed: Story = { args: runs[1] };
export const Passed: Story = { args: runs[2] };

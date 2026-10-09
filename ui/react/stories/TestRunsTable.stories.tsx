import type { Meta, StoryObj } from "@storybook/react-vite";
import { TestRunsTable } from "../src/index.js";
import { runs } from "./sample.js";

const meta = { title: "Panels/TestRunsTable", component: TestRunsTable, decorators: [(S) => <div className="card scroll-x" style={{ maxWidth: 760 }}><S /></div>] } satisfies Meta<typeof TestRunsTable>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ThreeRuns: Story = { args: { rows: runs } };
export const NoRuns: Story = { args: { rows: [] } };

import type { Meta, StoryObj } from "@storybook/react-vite";
import { Issue } from "../src/index.js";

const meta = { title: "Status/Issue", component: Issue, decorators: [(S) => <div className="issues" style={{ maxWidth: 560 }}><S /></div>] } satisfies Meta<typeof Issue>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Failure: Story = { args: { level: "err", text: "Flash failed: west flash exited with 2" } };
export const Warning: Story = { args: { level: "warn", text: "Flashed, boot not seen: no banner within 10 s" } };

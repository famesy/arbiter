import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tag } from "../src/index.js";

const meta = { title: "Status/Tag", component: Tag, decorators: [(S) => <div className="efield"><span className="label"><S /></span></div>] } satisfies Meta<typeof Tag>;
export default meta;
type Story = StoryObj<typeof meta>;

export const AppliesNow: Story = { args: { text: "applies now" } };
export const AfterRestart: Story = { args: { text: "after restart", restart: true } };

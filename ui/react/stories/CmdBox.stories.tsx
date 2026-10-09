import type { Meta, StoryObj } from "@storybook/react-vite";
import { CmdBox } from "../src/index.js";

const meta = { title: "Guide/CmdBox", component: CmdBox, decorators: [(S) => <div id="guide" style={{ maxWidth: 560 }}><S /></div>] } satisfies Meta<typeof CmdBox>;
export default meta;
type Story = StoryObj<typeof meta>;

export const InstallPlugin: Story = { args: { text: "/plugin marketplace add famesy/arbiter\n/plugin install arbiter@arbiter" } };

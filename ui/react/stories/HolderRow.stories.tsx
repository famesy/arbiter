import type { Meta, StoryObj } from "@storybook/react-vite";
import { HolderRow } from "../src/index.js";

const meta = { title: "Board/HolderRow", component: HolderRow, decorators: [(S) => <div className="boardbar st-leased"><div className="meta-row"><S /></div></div>] } satisfies Meta<typeof HolderRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Held: Story = { args: { holder: "claude: lte test", left: "12m 40s", op: "test · 1m 05s", reason: "run the LTE link tests after the modem fix" } };
export const Paused: Story = { args: { holder: "claude: lte test", paused: true, left: "on hold" } };
export const Free: Story = { args: { platform: "native_sim/native/64" } };

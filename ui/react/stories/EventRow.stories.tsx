import type { Meta, StoryObj } from "@storybook/react-vite";
import { EventRow } from "../src/index.js";

const meta = { title: "Panels/EventRow", component: EventRow, decorators: [(S) => <div className="card" style={{ maxWidth: 760 }}><div id="activity"><div id="feed"><S /></div></div></div>] } satisfies Meta<typeof EventRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Info: Story = { args: { time: "09:41:12", text: "claude: lte test started test on nrf9161dk-1" } };
export const Warning: Story = { args: { time: "09:39:30", text: "nrf9161dk-1 flash: ok, boot not seen (14s)", level: "warn" } };
export const Failure: Story = { args: { time: "09:33:02", text: "claude: lte test test on nrf9161dk-1: 11 passed, 1 failed (2m 41s)", level: "err" } };

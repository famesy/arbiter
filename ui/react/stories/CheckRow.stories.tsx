import type { Meta, StoryObj } from "@storybook/react-vite";
import { CheckRow } from "../src/index.js";

const meta = { title: "Settings/CheckRow", component: CheckRow, decorators: [(S) => <div className="checks" style={{ maxWidth: 760 }}><S /></div>] } satisfies Meta<typeof CheckRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Ok: Story = { args: { status: "OK", name: "west", detail: "west 1.4.0" } };
export const Warning: Story = { args: { status: "WARN", name: "nrf9161dk-1 · RTT", detail: "pylink not installed" } };
export const Failure: Story = { args: { status: "FAIL", name: "nucleo-h743 · probe", detail: "ST-Link 066DFF not found on USB" } };

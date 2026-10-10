import type { Meta, StoryObj } from "@storybook/react-vite";
import { Toast } from "../src/index.js";

const meta = { title: "Status/Toast", component: Toast, decorators: [(S) => <div style={{ display: "flex", alignItems: "flex-start" }}><S /></div>] } satisfies Meta<typeof Toast>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Info: Story = { args: { text: "You have nrf9161dk-1. The agent waits at the front of the queue." } };
export const Warning: Story = { args: { text: "Saved. 1 change applies after you restart arbiterd.", level: "warn" } };
export const Failure: Story = { args: { text: "Send: the board is offline", level: "err" } };

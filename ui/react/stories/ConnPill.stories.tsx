import type { Meta, StoryObj } from "@storybook/react-vite";
import { ConnPill } from "../src/index.js";

const meta = { title: "Status/ConnPill", component: ConnPill, decorators: [(S) => <header style={{ position: "static" }}><S /></header>] } satisfies Meta<typeof ConnPill>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Live: Story = { args: { up: true } };
export const Reconnecting: Story = { args: { up: false } };

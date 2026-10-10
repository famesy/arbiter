import type { Meta, StoryObj } from "@storybook/react-vite";
import { AgentRow } from "../src/index.js";

const meta = {
  title: "Board/AgentRow",
  component: AgentRow,
  decorators: [(S) => <aside className="rail" style={{ position: "static", width: 250 }}><div id="sessions"><S /></div></aside>],
} satisfies Meta<typeof AgentRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const HoldsABoard: Story = { args: { label: "claude: lte test", dot: "on", what: "nrf9161dk-1", title: "claude-code · fix/modem" } };
export const Waiting: Story = { args: { label: "codex: fota", what: "waiting for nrf9161dk-1" } };
export const NotResponding: Story = { args: { label: "claude: docs", dot: "warn", what: "not responding" } };

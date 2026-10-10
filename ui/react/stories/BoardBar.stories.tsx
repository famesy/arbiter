import type { Meta, StoryObj } from "@storybook/react-vite";
import { BoardActions, BoardBar, Button, HolderRow } from "../src/index.js";
import { chips, leasedActions, leasedHolder } from "./sample.js";

const meta = { title: "Board/BoardBar", component: BoardBar } satisfies Meta<typeof BoardBar>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Leased: Story = {
  args: { id: "nrf9161dk-1", state: "leased", status: { text: "testing", tone: "busy" }, actions: leasedActions, holder: leasedHolder, chips: chips() },
};

export const Free: Story = {
  args: {
    id: "sim-1", state: "available", status: { text: "free", tone: "free" },
    actions: <BoardActions main={<Button label="Take board" variant="primary" />} more={[<Button key="r" label="Reset" />, <Button key="m" label="Maintenance" />]} />,
    holder: <HolderRow platform="native_sim/native/64" />,
    chips: [{ label: "Queue", value: "0" }, { label: "Tests", value: "none" }, { label: "Activity" }],
  },
};

export const Paused: Story = {
  args: {
    id: "nrf9161dk-1", state: "paused", status: { text: "paused", tone: "busy" },
    actions: <BoardActions main={<Button label="Resume agent" variant="primary" />} more={[<Button key="t" label="Take over" />, <Button key="r" label="Revoke lease" variant="danger" />]} />,
    holder: <HolderRow holder="claude: lte test" paused left="on hold" />,
    chips: chips(),
  },
};

export const WithProblems: Story = {
  args: {
    id: "nrf9161dk-1", state: "leased", level: "err", status: { text: "agent not responding", tone: "warn" },
    actions: leasedActions,
    holder: <HolderRow holder="claude: lte test" left="ends in 42s" />,
    chips: chips("failed"),
    issues: [{ level: "warn", text: "claude: lte test stopped responding; the lease ends in 42s" }, { level: "err", text: "Last test run failed" }],
  },
};

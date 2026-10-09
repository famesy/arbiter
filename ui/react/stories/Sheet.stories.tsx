import type { Meta, StoryObj } from "@storybook/react-vite";
import { KeyValues, QueueTable, Sheet } from "../src/index.js";
import { queue } from "./sample.js";

const meta = { title: "Panels/Sheet", component: Sheet, decorators: [(S) => <div style={{ minHeight: 520, paddingTop: 24 }}><S /></div>] } satisfies Meta<typeof Sheet>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Queue: Story = { args: { open: true, title: "Queue", children: <QueueTable rows={queue} /> } };

export const BoardInfo: Story = {
  args: { open: true, title: "nrf9161dk-1", children: <KeyValues rows={[
    ["Platform", <span className="mono">nrf9161dk/nrf9161/ns</span>], ["Probe", <span className="mono">1050978819</span>],
    ["Console", "UART (.config)"], ["Last flash", "boot confirmed"], ["Shell", "48 commands"], ["Tags", "lte, modem"],
  ]} /> },
};

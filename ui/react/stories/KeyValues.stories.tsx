import type { Meta, StoryObj } from "@storybook/react-vite";
import { KeyValues } from "../src/index.js";

const meta = { title: "Board/KeyValues", component: KeyValues, decorators: [(S) => <div className="card" style={{ maxWidth: 520 }}><S /></div>] } satisfies Meta<typeof KeyValues>;
export default meta;
type Story = StoryObj<typeof meta>;

export const BoardInfo: Story = {
  args: { rows: [
    ["Platform", <span className="mono">nrf9161dk/nrf9161/ns</span>],
    ["Probe", <span className="mono">1050978819</span>],
    ["Ports", <span className="mono">/dev/ttyACM0, /dev/ttyACM1</span>],
    ["Console", "UART (.config)"],
    ["Last flash", "flashed, boot not seen", "warn"],
    ["Shell", "48 commands"],
    ["Power", "On · 3.70 V"],
  ] },
};

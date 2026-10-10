import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button, PowerPanel } from "../src/index.js";
import { history } from "./sample.js";

const meta = { title: "Panels/PowerPanel", component: PowerPanel, decorators: [(S) => <div className="card" style={{ maxWidth: 760 }}><S /></div>] } satisfies Meta<typeof PowerPanel>;
export default meta;
type Story = StoryObj<typeof meta>;

const controls = [
  <Button key="on" label="On" disabled />, <Button key="off" label="Off" />, <Button key="cy" label="Cycle" />, <span key="s" className="sep" />,
  <input key="v" type="number" defaultValue="3700" aria-label="Voltage in millivolts" />, <span key="u" className="muted">mV</span>, <Button key="set" label="Set voltage" />,
];
const base = {
  on: true, volts: "3.70 V", range: "safe range 3.0–4.2 V", controls,
  stats: { stats: [["Average", "1.12 mA"], ["Peak", "3.30 mA"], ["Min", "4.2 µA"], ["Window", "5.0 s"]] as Array<[string, string]> },
  history: { points: history, caption: "Last 24 measurements · solid average, dashed peak · top 3.30 mA" },
};

export const On: Story = { args: base };
export const Locked: Story = { args: { ...base, locked: true } };
export const Off: Story = { args: { ...base, on: false, volts: undefined, stats: undefined, history: undefined, empty: "No current measurement yet. Agents measure with measure_current." } };
export const Fault: Story = {
  args: { ...base, fault: "over current (52 mA > 50 mA)", stats: { warn: true, stats: [["Average", "51.2 mA"], ["Peak", "58.0 mA"]], note: <><b>Not a valid measurement: </b>a debugger was attached</> } },
};

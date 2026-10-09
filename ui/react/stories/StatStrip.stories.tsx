import type { Meta, StoryObj } from "@storybook/react-vite";
import { StatStrip } from "../src/index.js";

const meta = { title: "Panels/StatStrip", component: StatStrip, decorators: [(S) => <div className="card" style={{ maxWidth: 760 }}><S /></div>] } satisfies Meta<typeof StatStrip>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Current: Story = { args: { stats: [["Average", "1.12 mA"], ["Peak", "3.30 mA"], ["Min", "4.2 µA"], ["Window", "5.0 s"]] } };
export const NotValid: Story = { args: { warn: true, stats: [["Average", "51.2 mA"], ["Peak", "58.0 mA"]], note: <><b>Not a valid measurement: </b>a debugger was attached</> } };

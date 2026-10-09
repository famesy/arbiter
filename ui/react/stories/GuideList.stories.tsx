import type { Meta, StoryObj } from "@storybook/react-vite";
import { GuideList, Pill } from "../src/index.js";

const meta = { title: "Guide/GuideList", component: GuideList, decorators: [(S) => <div id="guide" style={{ maxWidth: 560 }}><S /></div>] } satisfies Meta<typeof GuideList>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Boards: Story = {
  args: { rows: [
    { name: "nrf9161dk-1", detail: "nrf9161dk/nrf9161/ns", end: <Pill text="free" tone="free" /> },
    { name: "sim-1", detail: "native_sim/native/64", end: <Pill text="in use" tone="busy" /> },
  ] },
};

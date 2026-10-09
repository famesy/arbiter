import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button, GuideRow, Pill } from "../src/index.js";

const meta = { title: "Guide/GuideRow", component: GuideRow, decorators: [(S) => <div id="guide" style={{ maxWidth: 560 }}><div className="guide-list"><S /></div></div>] } satisfies Meta<typeof GuideRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Board: Story = { args: { name: "nrf9161dk-1", detail: "nrf9161dk/nrf9161/ns", end: <Pill text="free" tone="free" /> } };
export const NewProbe: Story = { args: { name: "001050978819", mono: true, detail: "jlink", end: <Button label="Add" size="small" variant="primary" /> } };

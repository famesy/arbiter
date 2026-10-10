import type { Meta, StoryObj } from "@storybook/react-vite";
import { BootBlock } from "../src/index.js";

const meta = {
  title: "Terminal/BootBlock",
  component: BootBlock,
  decorators: [(S) => <pre id="term" tabIndex={0} className="fold" style={{ height: "auto", minHeight: 0 }}><S /></pre>],
} satisfies Meta<typeof BootBlock>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Folded: Story = { args: { summary: "Booted Zephyr OS v4.1.99-ncs1 (14 lines)", lines: [{ text: "*** Booting nRF Connect SDK v3.4.1 ***" }] } };
export const OpenWithWarnings: Story = {
  args: { summary: "Booted TF-M v2.1.1 (9 lines, has warnings)", level: "w", open: true, lines: [{ text: "[WRN] This device was provisioned with dummy keys.", kind: "w" }, { text: "Booting TF-M v2.1.1" }] },
};
export const WithErrors: Story = { args: { summary: "Booting (4 lines, has errors)", level: "e", lines: [{ text: "E: Image in the primary slot is not valid!", kind: "e" }] } };

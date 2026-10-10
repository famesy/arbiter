import type { Meta, StoryObj } from "@storybook/react-vite";
import { BootBlock, Terminal } from "../src/index.js";
import { termLines } from "./sample.js";

const meta = { title: "Terminal/Terminal", component: Terminal, decorators: [(S) => <div style={{ maxWidth: 960 }}><S /></div>] } satisfies Meta<typeof Terminal>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Live: Story = { args: { lines: termLines } };

export const AllDetailsShown: Story = { args: { lines: termLines, view: { fold: false, ts: true, prompt: true } } };

export const BootOutput: Story = {
  args: { lines: [
    <BootBlock summary="Booted Zephyr OS v4.1.99-ncs1 (14 lines)" lines={[{ text: "*** Booting nRF Connect SDK v3.4.1 ***" }]} />,
    <BootBlock summary="Booted TF-M v2.1.1 (9 lines, has warnings)" level="w" open lines={[{ text: "[WRN] This device was provisioned with dummy keys.", kind: "w" }, { text: "Booting TF-M v2.1.1" }]} />,
    <BootBlock summary="Booting (4 lines, has errors)" level="e" lines={[{ text: "E: Image in the primary slot is not valid!", kind: "e" }]} />,
  ] },
};

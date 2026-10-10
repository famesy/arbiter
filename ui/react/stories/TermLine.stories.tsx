import type { Meta, StoryObj } from "@storybook/react-vite";
import { TermLine } from "../src/index.js";

// Lines are styled by the terminal they sit in.
const meta = {
  title: "Terminal/TermLine",
  component: TermLine,
  decorators: [(S) => <pre id="term" tabIndex={0} className="fold" style={{ height: "auto", minHeight: 0 }}><S /></pre>],
} satisfies Meta<typeof TermLine>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Output: Story = { args: { text: "plain firmware output" } };
export const WithTimestamp: Story = { args: { timestamp: "[00:00:01.234,567] ", text: "<inf> app: with a log timestamp" } };
export const Warning: Story = { args: { kind: "w", text: "<wrn> app: a warning" } };
export const Failure: Story = { args: { kind: "e", text: "<err> app: an error" } };
export const ArbiterNote: Story = { args: { kind: "d", text: "[arbiter] a note from arbiter" } };
export const SentByYou: Story = { args: { kind: "h", sender: "[you]", mine: true, text: "> a line you sent" } };
export const SentByAgent: Story = { args: { kind: "a", sender: "[claude-1a2b]", text: "> a line an agent sent" } };
export const FromAnotherChannel: Story = { args: { source: "[rtt] ", text: "a line from another channel, on the All tab" } };

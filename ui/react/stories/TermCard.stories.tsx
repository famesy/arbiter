import type { Meta, StoryObj } from "@storybook/react-vite";
import { TermCard } from "../src/index.js";
import { channels, termLines } from "./sample.js";

const meta = { title: "Terminal/TermCard", component: TermCard, decorators: [(S) => <div style={{ maxWidth: 960 }}><S /></div>] } satisfies Meta<typeof TermCard>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Live: Story = {
  args: { channels, channel: "all", lines: termLines, hint: <><b>claude: lte test</b> keeps the board; your lines are marked as yours · Tab: 48 shell commands · ↑ history</> },
};

export const NoCommandHints: Story = {
  args: { channels, channel: "uart:app", lines: termLines.slice(1, 4), hint: "Sends to the uart:app · No command hints: the image was built without CONFIG_SHELL · ↑ history" },
};

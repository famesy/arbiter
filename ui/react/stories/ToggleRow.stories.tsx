import type { Meta, StoryObj } from "@storybook/react-vite";
import { ToggleRow } from "../src/index.js";

const meta = {
  title: "Controls/ToggleRow",
  component: ToggleRow,
  decorators: [(S) => <div className="card" style={{ maxWidth: 520 }}><S /></div>],
} satisfies Meta<typeof ToggleRow>;
export default meta;
type Story = StoryObj<typeof meta>;

export const On: Story = { args: { label: "Fold boot output", hint: "Shows bootloader and banner output as one line you can open.", checked: true } };
export const Off: Story = { args: { label: "Show log timestamps", hint: "Zephyr log times like [00:00:01.234,567]." } };

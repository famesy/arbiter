import type { Meta, StoryObj } from "@storybook/react-vite";
import { CheckMenu } from "../src/index.js";

const meta = {
  title: "Controls/CheckMenu",
  component: CheckMenu,
  decorators: [(S) => <div style={{ height: 180, display: "flex", justifyContent: "flex-end" }}><S /></div>],
} satisfies Meta<typeof CheckMenu>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ViewOptions: Story = {
  args: { open: true, options: [
    { id: "fold", label: "Fold boot output", checked: true },
    { id: "ts", label: "Show log timestamps", checked: false },
    { id: "prompt", label: "Show shell prompts", checked: false },
  ] },
};

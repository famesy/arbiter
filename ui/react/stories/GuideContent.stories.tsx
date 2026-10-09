import type { Meta, StoryObj } from "@storybook/react-vite";
import { GuideContent } from "../src/index.js";

// GuideContent fills the guide dialog; this shows it in an open one.
const meta = {
  title: "Guide/GuideContent",
  component: GuideContent,
  decorators: [(S) => <div style={{ minHeight: 420, paddingTop: 24 }}><dialog id="guide" open><S /></dialog></div>],
} satisfies Meta<typeof GuideContent>;
export default meta;
type Story = StoryObj<typeof meta>;

export const SecondStep: Story = { args: { steps: ["Boards", "Health check", "Connect agents"], step: 1, tint: "peach", body: <p className="lead">Checks the tools, probes and serial ports each board needs.</p> } };

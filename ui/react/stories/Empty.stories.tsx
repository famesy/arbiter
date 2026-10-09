import type { Meta, StoryObj } from "@storybook/react-vite";
import { Empty } from "../src/index.js";

const meta = { title: "Status/Empty", component: Empty } satisfies Meta<typeof Empty>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Queue: Story = { args: { text: "Nobody is waiting for this board." } };

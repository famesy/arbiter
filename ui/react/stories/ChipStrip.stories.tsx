import type { Meta, StoryObj } from "@storybook/react-vite";
import { ChipStrip } from "../src/index.js";
import { chips } from "./sample.js";

const meta = { title: "Board/ChipStrip", component: ChipStrip } satisfies Meta<typeof ChipStrip>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Leased: Story = { args: { chips: chips() } };
export const TestsFailed: Story = { args: { chips: chips("failed") } };

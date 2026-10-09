import type { Meta, StoryObj } from "@storybook/react-vite";
import { Tally } from "../src/index.js";

const meta = { title: "Guide/Tally", component: Tally } satisfies Meta<typeof Tally>;
export default meta;
type Story = StoryObj<typeof meta>;

export const SomeProblems: Story = { args: { ok: 14, warn: 1, fail: 1 } };
export const AllGood: Story = { args: { ok: 16 } };

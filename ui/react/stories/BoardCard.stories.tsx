import type { Meta, StoryObj } from "@storybook/react-vite";
import { BOARD_STATES, BoardCard } from "../src/index.js";
import { boards } from "./sample.js";

const meta = {
  title: "Board/BoardCard",
  component: BoardCard,
  argTypes: { state: { control: "select", options: [...BOARD_STATES] } },
  decorators: [(S) => <aside className="rail" style={{ position: "static", width: 250 }}><div id="boards"><S /></div></aside>],
} satisfies Meta<typeof BoardCard>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Leased: Story = { args: { ...boards[0], selected: true } };
export const Available: Story = { args: boards[1] };
export const Offline: Story = { args: boards[2] };
export const HeldByYou: Story = { args: boards[3] };
export const Maintenance: Story = { args: boards[4] };

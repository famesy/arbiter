import type { Meta, StoryObj } from "@storybook/react-vite";
import { TourItem } from "../src/index.js";

const meta = { title: "Guide/TourItem", component: TourItem, decorators: [(S) => <div id="guide" style={{ maxWidth: 560 }}><S /></div>] } satisfies Meta<typeof TourItem>;
export default meta;
type Story = StoryObj<typeof meta>;

export const First: Story = { args: { n: 1, title: "Type into the terminal", text: "Lines you send are marked as yours, even while an agent holds the board." } };

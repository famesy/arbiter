import type { Meta, StoryObj } from "@storybook/react-vite";
import { Logo } from "../src/index.js";

const meta = { title: "Brand/Logo", component: Logo } satisfies Meta<typeof Logo>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Mark: Story = { render: () => <div id="login" style={{ margin: 0 }}><h1 className="brand"><Logo /></h1></div> };

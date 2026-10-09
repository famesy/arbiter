import type { Meta, StoryObj } from "@storybook/react-vite";
import { NavTabs } from "../src/index.js";

const meta = {
  title: "Controls/NavTabs",
  component: NavTabs,
  args: { items: [{ id: "dash", label: "Dashboard" }, { id: "settings", label: "Settings", href: "#settings" }], active: "dash" },
  decorators: [(S) => <header style={{ position: "static" }}><S /></header>],
} satisfies Meta<typeof NavTabs>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Dashboard: Story = {};
export const Settings: Story = { args: { active: "settings" } };

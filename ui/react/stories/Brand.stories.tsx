import type { Meta, StoryObj } from "@storybook/react-vite";
import { Brand, Button, ConnPill, Menu, NavTabs } from "../src/index.js";

const meta = { title: "Brand/Brand", component: Brand } satisfies Meta<typeof Brand>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Wordmark: Story = { render: () => <header style={{ position: "static" }}><Brand /></header> };

export const LoginWordmark: Story = { render: () => <div id="login" style={{ margin: 0 }}><div className="card"><Brand as="h1" /></div></div> };

export const InHeader: Story = {
  render: () => (
    <header style={{ position: "static" }}>
      <Brand /><ConnPill up /><span className="spacer" />
      <NavTabs items={[{ id: "dash", label: "Dashboard" }, { id: "settings", label: "Settings", href: "#settings" }]} active="dash" />
      <Menu id="more" label="⋯" ariaLabel="More" items={[<Button key="p" label="Pause all agents" />, <Button key="g" label="Getting started guide" />]} />
    </header>
  ),
};

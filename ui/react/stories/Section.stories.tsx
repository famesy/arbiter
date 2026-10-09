import type { Meta, StoryObj } from "@storybook/react-vite";
import { CheckRow, Section, ToggleRow } from "../src/index.js";

const meta = { title: "Settings/Section", component: Section, decorators: [(S) => <div style={{ maxWidth: 980 }}><S /></div>] } satisfies Meta<typeof Section>;
export default meta;
type Story = StoryObj<typeof meta>;

export const HealthCheck: Story = {
  args: { id: "health", title: "Health check", sub: "The same checks as arbiter doctor. They read the setup and never touch a board.", children: (
    <div className="checks">
      <CheckRow status="FAIL" name="nucleo-h743 · probe" detail="ST-Link 066DFF not found on USB" />
      <CheckRow status="WARN" name="nrf9161dk-1 · RTT" detail="pylink not installed" />
      <CheckRow status="OK" name="west" detail="west 1.4.0" />
    </div>
  ) },
};

export const Preferences: Story = {
  args: { id: "prefs", title: "This browser", sub: "Saved in this browser only.", children: (
    <div className="prefs">
      <h3 style={{ marginTop: 0 }}>Terminal</h3>
      <ToggleRow label="Fold boot output" hint="Shows bootloader and banner output as one line you can open." checked />
      <ToggleRow label="Show log timestamps" hint="Zephyr log times like [00:00:01.234,567]." />
    </div>
  ) },
};

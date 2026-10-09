import type { Meta, StoryObj } from "@storybook/react-vite";
import { Alert, Button } from "../src/index.js";

const meta = { title: "Status/Alert", component: Alert } satisfies Meta<typeof Alert>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Approval: Story = {
  args: {
    level: "warn",
    text: <><b>claude: lte test</b> asks to erase <b>nrf9161dk-1</b></>,
    actions: [<Button key="a" label="Approve" variant="primary" />, <Button key="d" label="Deny" />, <Button key="s" label="Show board" size="small" />],
  },
};
export const Warning: Story = { args: { level: "warn", text: "Restart arbiterd to apply 2 saved changes: boards.nrf9161dk-1.runner, daemon.port." } };
export const Failure: Story = { args: { level: "err", text: "nrf9161dk-1 is offline (probe not found)" } };
export const Note: Story = { args: { level: "note", text: <>Saved to <code>~/.local/state/arbiter/config.toml</code>. Changes marked “applies now” take effect at once.</> } };

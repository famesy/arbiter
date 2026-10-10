import type { Meta, StoryObj } from "@storybook/react-vite";
import { BoardSettings, Button, Field, FieldGroup, Pill } from "../src/index.js";

const meta = { title: "Settings/BoardSettings", component: BoardSettings, decorators: [(S) => <div className="card set-section" style={{ maxWidth: 980 }}><S /></div>] } satisfies Meta<typeof BoardSettings>;
export default meta;
type Story = StoryObj<typeof meta>;

export const InUse: Story = {
  args: {
    id: "nrf9161dk-1", pills: <Pill text="in use" tone="busy" />, actions: <Button label="Edit" size="small" />,
    children: (
      <div className="groups">
        <FieldGroup title="Hardware"><Field label="Platform" value="nrf9161dk/nrf9161/ns" /><Field label="Driver" value="nrf" /></FieldGroup>
        <FieldGroup title="Power"><Field label="Supply" value="ppk2" /><Field label="Voltage range" value="3.00 V to 4.20 V" hint="Refused outside this range, for agents and you alike." /></FieldGroup>
      </div>
    ),
  },
};

export const PendingRestart: Story = { args: { id: "nrf5340dk-1", pills: <Pill text="starts after a restart" tone="warn" /> } };

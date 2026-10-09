import type { Meta, StoryObj } from "@storybook/react-vite";
import { Field, FieldGroup } from "../src/index.js";

const meta = { title: "Settings/FieldGroup", component: FieldGroup, decorators: [(S) => <div className="card" style={{ maxWidth: 420 }}><S /></div>] } satisfies Meta<typeof FieldGroup>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Hardware: Story = {
  args: { title: "Hardware", children: [<Field key="p" label="Platform" value="nrf9161dk/nrf9161/ns" />, <Field key="d" label="Driver" value="nrf" />, <Field key="s" label="Probe serial" value="1050978819" />] },
};

import type { Meta, StoryObj } from "@storybook/react-vite";
import { Field } from "../src/index.js";

const meta = { title: "Settings/Field", component: Field, decorators: [(S) => <div className="set-group" style={{ maxWidth: 320 }}><div className="fields"><S /></div></div>] } satisfies Meta<typeof Field>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Value: Story = { args: { label: "Platform", value: "nrf9161dk/nrf9161/ns" } };
export const WithHint: Story = { args: { label: "Mode", value: "auto", hint: "auto picks RTT only when the build has CONFIG_RTT_CONSOLE=y and no UART console." } };
export const Missing: Story = { args: { label: "Flash runner", value: "not reported yet", muted: true } };

import type { Meta, StoryObj } from "@storybook/react-vite";
import { CommandBar, Suggestions } from "../src/index.js";

const meta = { title: "Terminal/CommandBar", component: CommandBar, decorators: [(S) => <div style={{ maxWidth: 720 }}><S /></div>] } satisfies Meta<typeof CommandBar>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const WithSuggestions: Story = {
  decorators: [(S) => <div style={{ paddingTop: 180 }}><S /></div>],
  args: {
    input: <input defaultValue="kernel " placeholder="Type a command, Enter to send" />,
    suggest: <Suggestions active={1} options={[{ name: "reboot", help: "Reboot the system" }, { name: "threads", help: "List kernel threads" }, { name: "uptime", help: "Kernel uptime" }]} />,
  },
};

export const Disabled: Story = { args: { disabled: true, placeholder: "The board is offline" } };

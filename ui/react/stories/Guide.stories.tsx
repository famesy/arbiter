import type { Meta, StoryObj } from "@storybook/react-vite";
import { Button, CheckRow, CmdBox, Guide, GuideList, Pill, Tally, TourItem } from "../src/index.js";

const STEPS = ["Boards", "Health check", "Connect agents", "Using the board"];

const meta = {
  title: "Guide/Guide",
  component: Guide,
  parameters: { layout: "fullscreen" },
  args: { open: true, steps: STEPS },
  decorators: [(S) => <div style={{ minHeight: 780, paddingTop: 24 }}><S /></div>],
} satisfies Meta<typeof Guide>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Boards: Story = {
  args: { step: 0, tint: "sage", body: <>
    <p className="lead">arbiter shares your dev boards between AI agents and you. These boards are set up:</p>
    <GuideList rows={[
      { name: "nrf9161dk-1", detail: "nrf9161dk/nrf9161/ns", end: <Pill text="free" tone="free" /> },
      { name: "sim-1", detail: "native_sim/native/64", end: <Pill text="in use" tone="busy" /> },
    ]} />
    <p><b>1 probe</b> plugged in but not set up:</p>
    <GuideList rows={[{ name: "001050978819", mono: true, detail: "jlink", end: <Button label="Add" size="small" variant="primary" /> }]} />
    <div className="btn-row"><Button label="Add a simulated board" size="small" /><Button label="Open board settings" size="small" /></div>
  </> },
};

export const HealthCheck: Story = {
  args: { step: 1, tint: "peach", body: <>
    <p className="lead">Checks the tools, probes and serial ports each board needs. Probes held by an agent are left alone.</p>
    <Tally ok={14} warn={1} fail={1} />
    <div className="checks">
      <CheckRow status="FAIL" name="nucleo-h743 · probe" detail="ST-Link 066DFF not found on USB" />
      <CheckRow status="WARN" name="nrf9161dk-1 · RTT" detail="pylink not installed; RTT console unavailable" />
    </div>
    <Button label="Run again" size="small" />
  </> },
};

export const ConnectAgents: Story = {
  args: { step: 2, tint: "lilac", body: <>
    <p className="lead">Agents ask arbiter for a board, then flash, test and read the console through it.</p>
    <h3>Claude Code</h3>
    <CmdBox text={"/plugin marketplace add famesy/arbiter\n/plugin install arbiter@arbiter"} />
    <p className="muted">Then run <code>/arbiter:setup</code> once.</p>
  </> },
};

export const UsingTheBoard: Story = {
  args: { step: 3, tint: "pink", body: <>
    <p className="lead">Pick a board on the left. Its terminal fills the page.</p>
    <TourItem n={1} title="Type into the terminal" text="Lines you send are marked as yours, even while an agent holds the board." />
    <TourItem n={2} title="Tab suggests shell commands" text="They come from the flashed image. ↑ recalls earlier lines." />
    <TourItem n={3} title="Pause or take over" text="The button next to the board's name. More actions are under Actions." />
  </> },
};

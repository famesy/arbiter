import type { Meta, StoryObj } from "@storybook/react-vite";
import { AgentRow, Alert, BoardBar, BoardCard, Brand, Button, ConnPill, Menu, NavTabs, ProbeChip, TermCard } from "../src/index.js";
import { boards, channels, chips, leasedActions, leasedHolder, termLines } from "./sample.js";

// The whole dashboard page, put together from the components.
const meta = { title: "Pages/Dashboard", parameters: { layout: "fullscreen" } } satisfies Meta;
export default meta;

export const TerminalFirst: StoryObj = {
  render: () => (
    <div>
      <header>
        <Brand /><ConnPill up /><span className="spacer" />
        <NavTabs items={[{ id: "dash", label: "Dashboard" }, { id: "settings", label: "Settings", href: "#settings" }]} active="dash" />
        <Menu id="more" label="⋯" ariaLabel="More" items={[<Button key="p" label="Pause all agents" />, <Button key="g" label="Getting started guide" />]} />
      </header>
      <div className="wrap">
        <div id="alerts">
          <Alert level="warn" text={<><b>codex: fota</b> asks to erase <b>nrf9161dk-1</b></>} actions={[<Button key="a" label="Approve" variant="primary" />, <Button key="d" label="Deny" />]} />
        </div>
        <main className="desk">
          <aside className="rail">
            <h2>Boards</h2>
            <div id="boards">{boards.slice(0, 3).map((b, i) => <BoardCard key={b.id} {...b} selected={i === 0} />)}</div>
            <ProbeChip count={1} />
            <h2>Agents</h2>
            <div id="sessions">
              <AgentRow label="claude: lte test" dot="on" what="nrf9161dk-1" />
              <AgentRow label="codex: fota" what="waiting for nrf9161dk-1" />
            </div>
          </aside>
          <section id="detail">
            <BoardBar id="nrf9161dk-1" state="leased" status={{ text: "testing", tone: "busy" }} actions={leasedActions} holder={leasedHolder} chips={chips()} />
            <TermCard channels={channels.slice(0, 2)} lines={termLines}
              hint={<><b>claude: lte test</b> keeps the board; your lines are marked as yours · Tab: 48 shell commands · ↑ history</>} />
          </section>
        </main>
      </div>
    </div>
  ),
};
